"""Kiểm thử trò chơi camera; không truy cập webcam/cổng serial thật."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import AmazingHand_RPSGame as rps


def points(x=.25, y=.5):
    return [NS(x=x, y=y, z=0) for _ in range(21)]


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.config = rps.GameConfig()
        self.detector = rps.GestureDetector(Mock(), self.config)

    def test_consensus_labels_match_training_order_and_round_reset(self):
        for index, move in enumerate(('paper', 'rock', 'scissors')):
            self.detector.reset()
            scores = [.025, .025, .025]
            scores[index] = .95
            for _ in range(4):
                self.assertEqual(self.detector.accept(scores).move, rps.UNKNOWN)
            self.assertEqual(self.detector.accept(scores).move, move)
            self.detector.reset()
            self.assertEqual(self.detector.accept(scores).move, rps.UNKNOWN)

    def test_four_of_five_agreement(self):
        for scores in ([.95,.025,.025], [.95,.025,.025], [.025,.95,.025], [.95,.025,.025]):
            self.assertEqual(self.detector.accept(scores).move, rps.UNKNOWN)
        self.assertEqual(self.detector.accept([.95,.025,.025]).move, 'paper')

    def test_low_confidence_margin_and_malformed_outputs_rejected(self):
        for scores in ([.4,.3,.3], [float('nan'),0,1], [1,1,1], [-1,1,1], [1,0]):
            self.detector.reset()
            for _ in range(5):
                self.assertEqual(self.detector.accept(scores).move, rps.UNKNOWN)
        self.config.confidence_threshold = .5
        self.config.prediction_margin = .3
        self.assertEqual(self.detector.accept([.55,.4,.05]).move, rps.UNKNOWN)

    def test_rgb_nearest_resize_and_rescale_match_training(self):
        self.config.minimum_roi_std = 0
        def infer(batch):
            self.assertEqual(batch.shape, (1,150,150,3))
            self.assertEqual(batch.dtype, np.float32)
            np.testing.assert_allclose(batch[0,50,50], np.array([30,20,10])/255, atol=1e-7)
            return [.025,.025,.95]
        detector = rps.GestureDetector(Mock(infer=infer), self.config)
        frame = np.full((720,1280,3), (10,20,30), np.uint8)
        for _ in range(5):
            obs = detector.process(frame)
        self.assertEqual(obs.move, 'scissors')
        self.assertEqual(detector.process(None).move, rps.UNKNOWN)

    def test_blank_roi_never_infers_or_reuses_previous_vote(self):
        session = Mock()
        detector = rps.GestureDetector(session,self.config)
        for _ in range(5):
            detector.accept([.95,.025,.025])
        obs=detector.process(np.zeros((720,1280,3),np.uint8))
        self.assertEqual(obs.move,rps.UNKNOWN)
        self.assertFalse(detector.buffer)
        session.infer.assert_not_called()

    def test_single_snapshot_does_not_require_or_fabricate_temporal_votes(self):
        observation = self.detector.accept([.025,.95,.025], single_frame=True)
        self.assertEqual(observation.move, 'rock')
        self.assertEqual(len(self.detector.buffer), 0)
        self.assertEqual(self.detector.accept([.4,.3,.3], single_frame=True).move, rps.UNKNOWN)


class FakeCamera:
    def __init__(self, events):
        self.events, self.closed, self.seq = events, False, 0

    def get_frame(self, **kwargs):
        time.sleep(.001)
        self.seq += 1
        self.events.append('camera')
        return np.zeros((100, 160, 3), np.uint8), time.monotonic(), self.seq

    def close(self):
        self.closed = True


class FakeDetector:
    def __init__(self, events, move='rock'):
        self.events, self.move, self.samples = events, move, 0
        self.session = Mock()

    def reset(self):
        self.samples = 0

    def process(self, frame, single_frame=False):
        self.events.append('recognize')
        self.samples += 1
        return rps.GestureObservation(move=self.move if single_frame or self.samples >= 5 else rps.UNKNOWN,
                                      confidence=.95, latency_ms=2)


class FakeRobot:
    def __init__(self, events):
        self.events, self.closed = events, False
        self.moves = []
        self.reset_count = 0

    def execute_move(self, move):
        self.events.append('motor')
        self.moves.append(move)
        return {'confirmed': True, 'latency_ms': 7}

    def reset_pose(self):
        self.events.append('reset')
        self.reset_count += 1

    def cancel(self):
        self.events.append('cancel')

    def emergency_release(self):
        self.events.append('release')

    def close(self):
        self.closed = True


class GameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.events = []
        self.camera = FakeCamera(self.events)
        self.detector = FakeDetector(self.events)
        self.robot = FakeRobot(self.events)
        self.engine = Mock(closed=False)
        self.inputs = []
        def choose(history):
            self.events.append('choose')
            self.inputs.append(history)
            return rps.LockedDecision('rock', 'paper', 4, {'rock': .8, 'paper': .1, 'scissors': .1})
        self.engine.choose_move.side_effect = choose
        self.config = rps.GameConfig(countdown_seconds=0, gesture_timeout_seconds=.04,
                                     result_seconds=0, snapshot_delay_seconds=0, robot_enabled=False,
                                     require_confirmation=False)
        self.display = Mock()
        self.game = rps.RPSGame(self.config, self.camera, self.detector, self.engine,
                               self.robot, self.display, Path(self.temp.name)/'rounds.jsonl')
        self.addCleanup(self.game.close)

    def play(self):
        with redirect_stdout(io.StringIO()):
            return self.game.play_round()

    def test_two_rounds_reuse_resources_and_keep_score_history(self):
        first = self.play()
        second = self.play()
        self.assertTrue(first['valid'] and second['valid'])
        self.assertEqual(self.game.scoreboard, {'human': 0, 'robot': 2, 'draw': 0})
        self.assertEqual(len(self.inputs[0]), 0)
        self.assertEqual(len(self.inputs[1]), 1)
        self.assertEqual(self.robot.reset_count, 2)
        self.assertEqual(self.engine.choose_move.call_count, 2)
        self.assertIs(self.game.detector, self.detector)
        self.assertEqual(self.events.count('choose'), 2)
        self.assertLess(self.events.index('choose'), self.events.index('recognize'))
        self.assertEqual(first['state_trace'], ['READY', 'COUNTDOWN', 'COMMIT', 'REVEAL', 'VALIDATE', 'RESULT', 'RESET'])
        rows = [json.loads(l) for l in self.game.log_path.read_text(encoding='utf-8').splitlines()]
        self.assertEqual([r['round_id'] for r in rows], [1, 2])
        self.assertEqual(self.game.metrics()['laya_prediction_accuracy'], 1)

    def test_invalid_round_never_updates_valid_history_or_score(self):
        self.detector.move = rps.UNKNOWN
        result = self.play()
        self.assertEqual(result['result'], 'INVALID_ROUND')
        self.assertEqual(self.game.history, [])
        self.assertEqual(sum(self.game.scoreboard.values()), 0)
        self.assertEqual(self.game.metrics()['robot_loss_rate'], None)
        self.assertEqual(self.robot.reset_count, 1)

    def test_snapshot_is_classified_once_before_slow_motor_finishes(self):
        import threading
        completed = threading.Event()
        def slow_move(move):
            time.sleep(.08)  # Lâu hơn cửa sổ nhận diện .04 giây trong test.
            completed.set()
            return {'confirmed': True, 'latency_ms': 80}
        self.robot.execute_move = slow_move
        self.detector.process = Mock(side_effect=lambda frame, **kwargs: rps.GestureObservation(
            move='rock' if completed.is_set() else rps.UNKNOWN,
            label='Closed_Fist', confidence=.95, latency_ms=2,
            reason='' if completed.is_set() else 'Giu tay on dinh'))
        record = self.play()
        self.assertFalse(record['valid'])
        self.assertTrue(record['robot_confirmed'])
        self.assertEqual(record['gesture_diagnostics']['frames'], 1)
        self.detector.process.assert_called_once()
        self.assertTrue(self.detector.process.call_args.kwargs['single_frame'])

    def test_match_first_to_three_and_new_player_reset(self):
        with redirect_stdout(io.StringIO()):
            self.game.play_match()
        self.assertEqual(len(self.game.history), 3)
        self.assertEqual(self.game.scoreboard['robot'], 3)
        self.assertEqual(self.display.wait_continue.call_count, 3)
        self.assertTrue(self.display.wait_continue.call_args.kwargs['final'])
        first_session = self.game.session_id
        with redirect_stdout(io.StringIO()):
            self.game.play_match()
        self.assertEqual(len(self.game.history), 3)
        self.assertEqual(self.game.scoreboard['robot'], 3)
        self.assertNotEqual(first_session, self.game.session_id)
        self.assertEqual(len(self.inputs[3]), 0)
        self.assertEqual(self.robot.reset_count, 6)

    def test_invalid_attempt_does_not_consume_match_round(self):
        self.detector.move = rps.UNKNOWN
        self.display.wait_continue.side_effect = lambda *a, **k: setattr(self.detector, 'move', 'rock')
        with redirect_stdout(io.StringIO()):
            self.game.play_match()
        self.assertEqual(len(self.game.history), 3)
        self.assertEqual(len(self.game.records), 4)
        self.assertEqual(self.game.round_number, 4)

    def test_draws_continue_beyond_five_rounds_until_three_wins(self):
        self.detector.move='paper'
        def next_move(*args, **kwargs):
            if self.game.round_number >= 4:
                self.detector.move='rock'
        self.display.wait_continue.side_effect=next_move
        with redirect_stdout(io.StringIO()):
            self.game.play_match()
        self.assertEqual(self.game.scoreboard, {'human':0,'robot':3,'draw':4})
        self.assertEqual(len(self.game.history),7)
        self.assertEqual(self.display.wait_continue.call_count,7)

    def test_confirmation_rescues_unknown_and_is_given_to_laya_next_round(self):
        self.config.require_confirmation=True
        self.detector.move=rps.UNKNOWN
        self.display.confirm_move.return_value='scissors'
        first=self.play()
        self.assertTrue(first['valid'])
        self.assertEqual(first['model_human_move'],rps.UNKNOWN)
        self.assertTrue(first['model_overridden'])
        self.assertTrue(first['human_confirmed'])
        self.assertEqual(self.game.scoreboard['human'],1)
        self.assertEqual(self.game.metrics()['gesture_recognition_success_rate'],0)
        self.play()
        self.assertEqual(self.inputs[1][0]['human_move'],'scissors')
        self.assertEqual(self.inputs[1][0]['human_move_source'],'human_confirmation')

    def test_confirmation_interrupt_never_commits_result(self):
        self.config.require_confirmation=True
        self.display.confirm_move.side_effect=KeyboardInterrupt
        self.assertIsNone(self.play())
        self.assertEqual(self.game.history,[])
        self.assertEqual(sum(self.game.scoreboard.values()),0)
        self.assertFalse(self.game.log_path.exists())

    def test_human_can_win_match_using_confirmation_when_all_model_outputs_unknown(self):
        self.config.require_confirmation=True
        self.detector.move=rps.UNKNOWN
        self.display.confirm_move.return_value='scissors'
        with redirect_stdout(io.StringIO()):
            self.game.play_match()
        self.assertEqual(self.game.scoreboard,{'human':3,'robot':0,'draw':0})
        self.assertEqual(len(self.game.history),3)
        self.assertTrue(self.display.wait_continue.call_args.kwargs['final'])

    def test_confirmation_number_keys_map_rock_paper_scissors(self):
        import cv2
        display=rps.GameDisplay(rps.GameConfig(display_backend='opencv'))
        display.confirming=True
        frame=np.zeros((100,160,3),np.uint8)
        with patch.object(cv2,'namedWindow'),patch.object(cv2,'resizeWindow'), \
                patch.object(cv2,'setMouseCallback'),patch.object(cv2,'imshow'), \
                patch.object(cv2,'getWindowProperty',return_value=1), \
                patch.object(cv2,'waitKey',side_effect=[ord('1'),ord('2'),ord('3')]):
            for move in rps.MOVES:
                display.begin_confirmation()
                display.show(frame,'VALIDATE',force=True)
                self.assertEqual(display.confirmed_move,move)

    def test_confirmation_mouse_buttons_map_rock_paper_scissors(self):
        import cv2
        self.config.show_confirmation_buttons=True
        display=rps.GameDisplay(self.config)
        display.confirming=True
        for index,move in enumerate(rps.MOVES):
            display.begin_confirmation()
            display._mouse(cv2.EVENT_LBUTTONUP,70+index*225,970,0,None)
            self.assertEqual(display.confirmed_move,move)

    def test_confirmation_is_accepted_at_reveal_before_capture_and_motor_completion(self):
        self.config.require_confirmation=True
        display=rps.GameDisplay(self.config)
        self.game.display=display
        phase=[]
        def show(frame,state,*args,**kwargs):
            if state=='REVEAL' and display.confirmed_move is None:
                self.assertTrue(display.confirming)
                self.assertEqual(self.events.count('recognize'),0)
                self.assertEqual(self.events.count('choose'),1)
                display.confirmed_move='scissors'
                phase.append(state)
        original=self.robot.execute_move
        def slow_move(move):
            time.sleep(.04)
            return original(move)
        self.robot.execute_move=slow_move
        with patch.object(display,'show',side_effect=show):
            record=self.play()
        self.assertEqual(phase,['REVEAL'])
        self.assertTrue(record['robot_confirmed'])
        self.assertEqual(record['human_move'],'scissors')
        self.assertEqual(record['model_human_move'],'rock')
        self.assertEqual(record['result'],'HUMAN_WIN')
        self.assertFalse(display.confirming)

    def test_app_reset_reuses_resources_and_resets_player_without_rerunning_cell(self):
        self.display.wait_action.side_effect=['start','start','start','reset','start','quit']
        self.game.run_app()
        self.assertEqual(self.robot.reset_count,6)
        self.assertEqual(self.game.scoreboard,{'human':0,'robot':1,'draw':0})
        self.assertEqual(len(self.game.history),1)
        self.assertEqual(len(self.inputs[3]),0)
        self.assertIs(self.game.camera,self.camera)
        self.assertIs(self.game.decision_engine,self.engine)
        self.assertFalse(self.game.closed)
        self.assertFalse(self.camera.closed)
        self.assertTrue((self.game.log_path.parent/'rps_ui_session.log').is_file())

    def test_reset_match_is_blocked_during_motion(self):
        self.game.busy=True
        with self.assertRaises(RuntimeError):
            self.game.reset_match()
        self.game.busy=False

    def test_enter_continues_without_clickable_continue_button(self):
        import cv2
        display=rps.GameDisplay(rps.GameConfig(display_backend='opencv'))
        display.enter_prompt='ENTER: VAN TIEP THEO'
        with patch.object(cv2,'namedWindow'),patch.object(cv2,'resizeWindow'), \
                patch.object(cv2,'setMouseCallback'),patch.object(cv2,'imshow'), \
                patch.object(cv2,'getWindowProperty',return_value=1),patch.object(cv2,'waitKey',return_value=13):
            display.show(np.zeros((100,160,3),np.uint8),'READY',force=True)
        self.assertTrue(display.clicked)
        self.assertEqual(display.button_text,'')

    def test_game_defaults_fast_motion_and_curled_ready_pose(self):
        config=rps.GameConfig()
        self.assertEqual(config.speed_deg_s,160)
        self.assertEqual(config.reset_move,'rock')

    def test_header_reset_and_quit_buttons_respect_busy_state(self):
        import cv2
        display=rps.GameDisplay(self.config)
        display.app_active=True
        display._mouse(cv2.EVENT_LBUTTONUP,1500,120,0,None)
        self.assertIsNone(display.action)
        display.allow_reset=True
        display._mouse(cv2.EVENT_LBUTTONUP,1500,120,0,None)
        self.assertEqual(display.action,'reset')
        display._mouse(cv2.EVENT_LBUTTONUP,1800,120,0,None)
        self.assertEqual(display.action,'quit')

    def test_motor_starts_after_countdown_and_only_one_snapshot_is_classified(self):
        self.config.countdown_seconds = .04
        motor_states=[]
        original=self.robot.execute_move
        self.robot.execute_move=lambda move: (motor_states.append(self.game.state), original(move))[1]
        record = self.play()
        self.assertTrue(record['valid'])
        self.assertEqual(motor_states, ['REVEAL'])
        self.assertLess(self.events.index('motor'), self.events.index('recognize'))
        self.assertEqual(self.events.count('recognize'), 1)
        self.assertEqual(record['recognition_mode'], 'single_snapshot')
        self.assertTrue(Path(record['snapshot_path']).is_file())
        self.assertEqual(record['gesture_diagnostics']['frames'], 1)
        states = [c.args[1] for c in self.display.show.call_args_list]
        self.assertIn('COUNTDOWN', states)

    def test_snapshot_delay_is_respected_and_frozen_frame_kept(self):
        self.config.snapshot_delay_seconds=.03
        record=self.play()
        self.assertGreaterEqual(record['snapshot_after_reveal_ms'],30)
        self.assertIsNotNone(self.game.snapshot_frame)
        np.testing.assert_array_equal(self.game.last_frame,self.game.snapshot_frame)

    def test_dashboard_dimensions_and_continue_hit_area(self):
        import cv2
        display = rps.GameDisplay(rps.GameConfig(display_backend='opencv'))
        frame = np.zeros((720, 1280, 3), np.uint8)
        with patch.object(cv2, 'namedWindow'), patch.object(cv2, 'resizeWindow'), \
                patch.object(cv2, 'setMouseCallback'), patch.object(cv2, 'imshow') as show, \
                patch.object(cv2, 'waitKey', return_value=-1), \
                patch.object(cv2, 'getWindowProperty', return_value=1):
            display.show(frame, 'COUNTDOWN', extra='3', force=True)
        self.assertEqual(show.call_args.args[1].shape, (1080, 1920, 3))
        display.button_text = 'TIEP TUC'
        display._mouse(cv2.EVENT_LBUTTONUP, 1500, 970, 0, None)
        self.assertTrue(display.clicked)
        display.clicked = False
        display._mouse(cv2.EVENT_LBUTTONUP, 20, 20, 0, None)
        self.assertFalse(display.clicked)

    def test_model_error_does_not_move_robot(self):
        self.engine.choose_move.side_effect = RuntimeError('model error')
        result = self.play()
        self.assertFalse(result['valid'])
        self.assertEqual(self.robot.moves, [])
        self.assertIn('model error', result['error'])

    def test_motor_error_does_not_score_or_leave_torque_enabled(self):
        self.robot.execute_move = Mock(side_effect=RuntimeError('Parsing error'))
        result = self.play()
        self.assertFalse(result['valid'])
        self.assertEqual(self.game.history, [])
        self.assertIn('release', self.events)

    def test_camera_error_and_keyboard_interrupt_cleanup(self):
        self.camera.get_frame = Mock(side_effect=RuntimeError('camera lost'))
        result = self.play()
        self.assertFalse(result['valid'])
        self.assertIn('release', self.events)
        self.assertEqual(self.game.history, [])

    def test_interrupt_is_not_logged_or_scored(self):
        self.detector.process = Mock(side_effect=KeyboardInterrupt)
        self.assertIsNone(self.play())
        self.assertFalse(self.game.log_path.exists())
        self.assertEqual(self.game.history, [])
        self.assertIn('release', self.events)

    def test_metrics_do_not_treat_invalid_as_loss(self):
        self.play()
        self.detector.move = rps.UNKNOWN
        self.play()
        metrics = self.game.metrics()
        self.assertEqual(metrics['valid_rounds'], 1)
        self.assertEqual(metrics['robot_win_rate'], 1)
        self.assertEqual(metrics['robot_loss_rate'], 0)
        self.assertEqual(metrics['gesture_recognition_success_rate'], .5)


class AdapterTests(unittest.TestCase):
    def test_camera_falls_back_to_available_index_without_manual_configuration(self):
        import cv2
        config=rps.GameConfig(robot_enabled=False)
        unavailable=Mock()
        unavailable.isOpened.return_value=False
        available=Mock()
        available.isOpened.return_value=True
        frame=np.zeros((720,1280,3),np.uint8)
        available.read.return_value=(True,frame)
        available.get.return_value=30
        camera=rps.CameraStream(config)
        with patch.object(cv2,'VideoCapture',side_effect=[unavailable,available]), \
                patch.object(rps.threading,'Thread'), \
                patch.object(camera,'get_frame',return_value=(frame,time.monotonic(),1)), \
                redirect_stdout(io.StringIO()):
            camera.open()
            self.assertEqual(config.camera_id,1)
            self.assertIs(camera.capture,available)
            unavailable.release.assert_called_once()
            available.release.assert_not_called()
            camera.close()
            available.release.assert_called_once()

    def test_inline_display_creates_one_output_per_round_and_updates_in_place(self):
        display = rps.GameDisplay(rps.GameConfig(display_backend='notebook'))
        frame = np.zeros((100, 160, 3), np.uint8)
        handle = Mock()
        with patch('IPython.display.display', return_value=handle) as show:
            for _ in range(2):
                display.start_round()
                display.show(frame, 'READY', force=True)
                display.show(frame, 'REVEAL', force=True)
        self.assertEqual(show.call_count, 2)
        self.assertEqual(handle.update.call_count, 2)

    def test_laya_sees_only_previous_history_and_counter_is_locked(self):
        agent = Mock()
        agent.predict.return_value = {'answers': {'prediction': {
            'choice': 'scissors', 'probabilities': {'rock': .1, 'paper': .1, 'scissors': .8}}}}
        rng=Mock()
        rng.choices.return_value=['rock']
        engine = rps.LayaDecisionEngine(agent, rng=rng)
        history = [{'human_move': 'paper', 'robot_move': 'rock', 'secret_frame': object()}]
        result = engine.choose_move(history)
        state = agent.predict.call_args.args[0]
        self.assertNotIn('secret_frame', state['previous_rounds'][0])
        self.assertEqual(state['current_human_move'], 'unknown; the round has not started')
        self.assertEqual((result.predicted_human_move, result.robot_move), ('scissors', 'rock'))
        with self.assertRaises(Exception):
            result.robot_move = 'paper'

    def test_laya_sampling_keeps_three_moves_possible_even_with_peaked_prediction(self):
        import random
        agent=Mock()
        agent.predict.return_value={'answers':{'prediction':{
            'choice':'rock','probabilities':{'rock':1.,'paper':0.,'scissors':0.}}}}
        engine=rps.LayaDecisionEngine(agent, rng=random.Random(123))
        decisions=[engine.choose_move(()) for _ in range(100)]
        self.assertEqual(set(d.robot_move for d in decisions),set(rps.MOVES))
        self.assertTrue(all(d.predicted_human_move=='rock' for d in decisions))
        self.assertAlmostEqual(decisions[0].robot_probabilities['paper'],.8)
        self.assertAlmostEqual(decisions[0].robot_probabilities['rock'],.1)
        self.assertAlmostEqual(decisions[0].robot_probabilities['scissors'],.1)

    def test_full_exploration_is_uniform_and_invalid_exploration_is_rejected(self):
        agent=Mock()
        agent.predict.return_value={'answers':{'prediction':{
            'choice':'scissors','probabilities':{'rock':.1,'paper':.1,'scissors':.8}}}}
        engine=rps.LayaDecisionEngine(agent,rps.GameConfig(laya_exploration=1))
        decision=engine.choose_move(())
        for value in decision.robot_probabilities.values():
            self.assertAlmostEqual(value,1/3)
        with self.assertRaises(ValueError):
            rps.GameConfig(laya_exploration=1.1).validate()

    def test_disabled_robot_never_constructs_serial_controller(self):
        with patch('rustypot.Scs0009PyController') as serial, redirect_stdout(io.StringIO()):
            robot = rps.AmazingHandRobotAdapter(rps.GameConfig(robot_enabled=False)).connect()
            robot.execute_move('paper')
            robot.reset_pose()
            robot.close()
            robot.connect()
            self.assertTrue(robot.execute_move('rock')['confirmed'])
            robot.close()
        serial.assert_not_called()

    def test_persistent_robot_connection_not_recreated_between_moves(self):
        with patch('rustypot.Scs0009PyController') as constructor, \
             patch('AmazingHand_Notebook.NotebookHand.inspect', return_value=[]), \
             patch('AmazingHand_LayaRPS.perform_move') as perform, \
             patch('AmazingHand_Notebook.NotebookHand.release'), redirect_stdout(io.StringIO()):
            robot = rps.AmazingHandRobotAdapter(rps.GameConfig()).connect()
            for move in rps.MOVES:
                robot.execute_move(move)
                robot.connect()
            self.assertEqual(constructor.call_count, 1)
            self.assertEqual(perform.call_count, 3)
            constructor.return_value.close.assert_not_called()
            robot.close()
            constructor.return_value.close.assert_called_once_with()

    def test_abort_never_blocks_torque_release(self):
        import threading
        abort = threading.Event()
        abort.set()
        raw = Mock()
        proxy = rps._AbortableController(raw, abort)
        with self.assertRaises(RuntimeError):
            proxy.sync_write_goal_position([1], [0])
        proxy.write_torque_enable(1, 0)
        raw.sync_write_goal_position.assert_not_called()
        raw.write_torque_enable.assert_called_once_with(1, 0)


if __name__ == '__main__':
    unittest.main()
