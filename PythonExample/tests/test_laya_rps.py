"""Verify decision-to-pose routing without opening any hardware port."""
from contextlib import redirect_stdout
import io
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import AmazingHand_LayaRPS as rps
from AmazingHand_Notebook import NotebookHand


def fake_agent(move):
    agent = Mock()
    agent.predict.return_value = {'answers': {'move': {
        'choice': move, 'confidence': .9,
        'probabilities': {m: .8 if m == move else .1 for m in rps.MOVES},
    }}}
    return agent


class LayaRPSTests(unittest.TestCase):
    def test_all_nine_game_outcomes(self):
        expected = {
            'rock': ('draw', 'laya_win', 'player_win'),
            'paper': ('player_win', 'draw', 'laya_win'),
            'scissors': ('laya_win', 'player_win', 'draw'),
        }
        for player in rps.MOVES:
            for robot, answer in zip(rps.MOVES, expected[player]):
                self.assertEqual(rps.outcome(player, robot), answer)

    def test_input_accepts_vietnamese_and_english(self):
        for text, move in [(' BÚA ', 'rock'), ('bao', 'paper'), ('Kéo', 'scissors'),
                           ('ROCK', 'rock'), ('2', 'paper'), ('3', 'scissors')]:
            self.assertEqual(rps.normalize_move(text), move)

    def test_invalid_player_input_stops_before_inference_or_movement(self):
        agent, hand = Mock(), Mock()
        with self.assertRaises(ValueError):
            rps.run_round(agent, hand, 'game', [], player_move='invalid')
        agent.predict.assert_not_called()
        self.assertEqual(hand.mock_calls, [])

    def test_game_uses_actual_model_choice_and_scores_only_completed_rounds(self):
        agent, hand = fake_agent('rock'), Mock(port='FAKE', dry_run=False)
        history = []
        with redirect_stdout(io.StringIO()):
            result = rps.run_round(agent, hand, 'game', history, player_move='bao')
        self.assertEqual(result['outcome'], 'player_win')  # Never replace losing model choice.
        self.assertEqual(agent.predict.call_args.args[0]['player_move'], 'paper')
        self.assertEqual(agent.predict.call_args.args[1], rps.GAME_QUESTIONS)
        hand.close_all.assert_called_once_with()
        self.assertEqual(rps.scoreboard(history)['player_win'], 1)
        history.extend([dict(result, completed=False), dict(result, dry_run=True)])
        self.assertEqual(rps.scoreboard(history)['player_win'], 1)

    def test_all_three_map_to_exact_calibrated_fingers(self):
        for move in rps.MOVES:
            with self.subTest(move=move):
                hand = NotebookHand(spread=0)
                with patch.object(hand, '_hold') as hold:
                    rps.perform_move(hand, move)
                self.assertEqual(hold.call_args.args[0], hand.targets(rps.RAISED[move]))

    def test_invalid_decision_never_moves_hardware(self):
        hand = Mock()
        with self.assertRaises(ValueError):
            rps.run_round(fake_agent('other'), hand, 'demo', [])
        self.assertEqual(hand.mock_calls, [])

    def test_invalid_probabilities_never_moves_hardware(self):
        agent = fake_agent('rock')
        agent.predict.return_value['answers']['move']['probabilities']['rock'] = float('nan')
        hand = Mock()
        with self.assertRaises(ValueError):
            rps.run_round(agent, hand, 'demo', [])
        self.assertEqual(hand.mock_calls, [])

    def test_each_model_choice_is_logged_and_executed_without_replacement(self):
        for move, method in [('rock', 'close_all'), ('paper', 'open_all'), ('scissors', 'scissors')]:
            hand = Mock(port='FAKE', dry_run=False)
            history, statuses = [], []
            with redirect_stdout(io.StringIO()) as output:
                result = rps.run_round(fake_agent(move), hand, 'demo', history,
                                       lambda r: statuses.append(r['hardware_status']))
            getattr(hand, method).assert_called_once_with()
            self.assertEqual(result['move'], move)
            self.assertEqual(len(history), 1)
            self.assertEqual(statuses[0], 'pending')
            self.assertIn('HOÀN TẤT', statuses[-1])
            self.assertIn('[LAYA]', output.getvalue())
            hand.release.assert_not_called()

    def test_hardware_failure_releases_and_does_not_report_success(self):
        hand = Mock(port='FAKE', dry_run=False)
        hand.open_all.side_effect = RuntimeError('servo offline')
        history = []
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'servo offline'):
            rps.run_round(fake_agent('paper'), hand, 'demo', history)
        hand.release.assert_called_once_with()
        self.assertIn('LỖI', history[0]['hardware_status'])
        self.assertNotIn('HOÀN TẤT', history[0]['hardware_status'])

    def test_history_is_bounded_in_model_input(self):
        agent = fake_agent('paper')
        rps.decide(agent, 'new context', [{'move': 'rock'}] * 25)
        state, questions = agent.predict.call_args.args
        self.assertEqual(len(state['recent_moves']), 10)
        self.assertEqual(state['context'], 'new context')
        self.assertEqual(set(questions['move']['criteria']), set(rps.MOVES))


if __name__ == '__main__':
    unittest.main()
