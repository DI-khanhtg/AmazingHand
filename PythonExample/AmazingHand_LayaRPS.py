"""Local Laya inference and a bounded Rock/Paper/Scissors hardware adapter."""

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time

MODEL_ID = 'convaiinnovations/laya'
MODEL_REVISION = '7b928d828b7b0e022f929d9bd2e44165aa270148'
MOVES = ('rock', 'paper', 'scissors')
RAISED = {'rock': (), 'paper': ('index', 'middle', 'ring', 'thumb'),
          'scissors': ('index', 'middle')}
LABELS = {'rock': 'ROCK — BÚA', 'paper': 'PAPER — BAO', 'scissors': 'SCISSORS — KÉO'}
QUESTIONS = {
    'move': {
        'type': 'choice',
        'instructions': 'Choose exactly one gesture for the robot hand to perform now. '
                        'Use the current task and context. All three gestures are valid.',
        'criteria': {
            'rock': 'Rock: curl all four fingers into a fist.',
            'paper': 'Paper: extend all four fingers.',
            'scissors': 'Scissors: extend index and middle; curl ring and thumb.',
        },
    },
}
GAME_QUESTIONS = {
    'move': {
        'type': 'choice',
        'instructions': 'Play Rock Paper Scissors against the human. The human move is '
                        'already revealed in player_move. Choose the robot move that wins: '
                        'rock beats scissors, paper beats rock, scissors beats paper.',
        'criteria': {
            'rock': 'Play rock. Rock beats scissors, ties rock, loses to paper.',
            'paper': 'Play paper. Paper beats rock, ties paper, loses to scissors.',
            'scissors': 'Play scissors. Scissors beats paper, ties scissors, loses to rock.',
        },
    },
}
OUTCOMES = {'player_win': 'BẠN THẮNG', 'laya_win': 'LAYA THẮNG', 'draw': 'HÒA'}


def normalize_move(value):
    import unicodedata
    if not isinstance(value, str):
        raise ValueError('Nhập rock/paper/scissors hoặc búa/bao/kéo (1/2/3).')
    plain = ''.join(c for c in unicodedata.normalize('NFKD', value.strip().lower())
                    if not unicodedata.combining(c))
    aliases = {'rock': 'rock', 'bua': 'rock', '1': 'rock',
               'paper': 'paper', 'bao': 'paper', '2': 'paper',
               'scissors': 'scissors', 'keo': 'scissors', '3': 'scissors'}
    if plain not in aliases:
        raise ValueError('Nước không hợp lệ. Nhập rock/paper/scissors hoặc búa/bao/kéo (1/2/3).')
    return aliases[plain]


def outcome(player_move, laya_move):
    if player_move not in MOVES or laya_move not in MOVES:
        raise ValueError('Cannot score an invalid move.')
    if player_move == laya_move:
        return 'draw'
    return 'player_win' if (player_move, laya_move) in {
        ('rock', 'scissors'), ('paper', 'rock'), ('scissors', 'paper'),
    } else 'laya_win'


def scoreboard(history):
    totals = {key: 0 for key in OUTCOMES}
    for item in history:
        if item.get('completed') and not item.get('dry_run') and item.get('outcome') in totals:
            totals[item['outcome']] += 1
    return totals


def ensure_model(directory, offline=False):
    """Download only the English checkpoint; reuse a completed local copy offline."""
    from huggingface_hub import snapshot_download

    directory = Path(directory).resolve()
    required = ('rl_agent_config.json', 'model.safetensors', 'encoder/config.json',
                'tokenizer/tokenizer.json', 'tokenizer/tokenizer_config.json')
    marker = directory / '.amazinghand-ready.json'
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding='utf-8'))
            ready = (data['model_id'] == MODEL_ID and data['revision'] == MODEL_REVISION
                     and all((directory / name).is_file()
                             and (directory / name).stat().st_size == data['sizes'][name]
                             and data['sizes'][name] > 0 for name in required))
            if ready:
                print(f'[MODEL] Dùng weights local: {directory}', flush=True)
                return directory
        except (OSError, ValueError, KeyError, TypeError):
            pass
    print('[MODEL] Kiểm tra/tải checkpoint; lần đầu cần Internet (~808 MB).', flush=True)
    snapshot_download(
        repo_id=MODEL_ID, revision=MODEL_REVISION, local_dir=str(directory),
        allow_patterns=['rl_agent_config.json', 'model.safetensors',
                        'encoder/config.json', 'tokenizer/*'],
        local_files_only=offline,
    )
    missing = [name for name in required
               if not (directory / name).is_file() or (directory / name).stat().st_size == 0]
    if missing:
        raise RuntimeError(f'Checkpoint chưa đầy đủ: {missing}. Chạy lại cell tải model khi có Internet.')
    marker.write_text(json.dumps({
        'model_id': MODEL_ID, 'revision': MODEL_REVISION,
        'sizes': {name: (directory / name).stat().st_size for name in required},
    }, indent=2), encoding='utf-8')
    return directory


def decide(agent, context, history=(), player_move=None):
    """Use Laya's choice directly: no random choice or rule-based replacement."""
    state = {
        'task': 'Select a Rock, Paper, or Scissors gesture for AmazingHand to demonstrate.',
        'context': context,
        'recent_moves': [item['move'] for item in history[-10:]],
        'available_fingers': ['index', 'middle', 'ring', 'thumb'],
    }
    questions = QUESTIONS
    if player_move is not None:
        player_move = normalize_move(player_move)
        state.update(
            task='Choose the winning robot move against the revealed human move.',
            player_move=player_move,
            rules='Rock beats scissors. Paper beats rock. Scissors beats paper. Same move is a draw.',
            recent_rounds=[{'player_move': item['player_move'], 'laya_move': item['move'],
                            'outcome': item['outcome']} for item in history
                           if item.get('completed') and item.get('player_move')][-5:],
        )
        questions = GAME_QUESTIONS
    started = time.perf_counter()
    raw = agent.predict(state, questions)
    elapsed = time.perf_counter() - started
    answer = raw['answers']['move']
    move = answer.get('choice')
    if move not in MOVES:
        raise ValueError(f'Laya trả về nước không hợp lệ: {move!r}. Không gửi lệnh servo.')
    probabilities = answer.get('probabilities', {})
    if set(probabilities) != set(MOVES) or not all(
        isinstance(p, (int, float)) and math.isfinite(p) and 0 <= p <= 1
        for p in probabilities.values()
    ) or abs(sum(probabilities.values()) - 1) > .01:
        raise ValueError('Phân phối xác suất Laya không hợp lệ. Không gửi lệnh servo.')
    if probabilities[move] < max(probabilities.values()) - .0002:
        raise ValueError('Choice và xác suất Laya không nhất quán. Không gửi lệnh servo.')
    return {
        'time_utc': datetime.now(timezone.utc).isoformat(),
        'move': move, 'probabilities': probabilities,
        'confidence': answer.get('confidence'), 'inference_seconds': elapsed,
        'state': state, 'raw': raw, 'hardware_status': 'pending',
        'player_move': player_move,
        'outcome': outcome(player_move, move) if player_move else None,
        'completed': False,
    }


def perform_move(hand, move):
    """Allow only three pre-calibrated poses; the model never supplies servo angles."""
    if move not in MOVES:
        raise ValueError(f'Unknown move: {move!r}')
    if move == 'rock':
        hand.close_all()
    elif move == 'paper':
        hand.open_all()
    else:
        # Use exactly the same calibrated endpoints as Paper; no spread offsets.
        hand.scissors()


def result_html(result):
    """Small vector hand diagram with four fingers in physical helper order."""
    from html import escape
    move = result['move']
    fingers = ''
    for i, name in enumerate(('index', 'middle', 'ring', 'thumb')):
        up = name in RAISED[move]
        x = 36 + i * 64
        fingers += (f'<rect x="{x}" y="{20 if up else 100}" width="42" '
                    f'height="{135 if up else 55}" rx="18" fill="{chr(35)}38bdf8"/>'
                    f'<text x="{x+21}" y="240" text-anchor="middle" '
                    f'font-size="13" fill="currentColor">{name}</text>')
    probs = ' · '.join(f'{name}: {result["probabilities"][name]:.1%}' for name in MOVES)
    game = ''
    if result.get('player_move'):
        game = (f'<p>Bạn: <strong>{escape(LABELS[result["player_move"]])}</strong> · '
                f'Laya: <strong>{escape(LABELS[move])}</strong></p>'
                f'<p><strong>{escape(OUTCOMES[result["outcome"]])}</strong>'
                f'{"" if result.get("completed") else " (chờ bàn tay thực hiện)"}</p>')
    return (f'<div style="border:1px solid #38bdf8;border-radius:12px;padding:16px">'
            f'<h2 style="margin:0">{escape(LABELS[move])}</h2>'
            f'{game}'
            f'<p>{escape(result["hardware_status"])}</p>'
            f'<svg viewBox="0 0 300 255" width="300" role="img" '
            f'aria-label="{escape(LABELS[move])}">'
            f'<rect x="30" y="140" width="250" height="75" rx="24" fill="#0284c7"/>'
            f'{fingers}</svg><p>{escape(probs)}</p></div>')


def run_round(agent, hand, context, history, display_result=None, player_move=None):
    """One click: infer, show the decision, move, and report verified completion."""
    result = decide(agent, context, history, player_move=player_move)
    result['dry_run'] = hand.dry_run
    if result['player_move']:
        print(f'[PLAYER] Nước của bạn: {LABELS[result["player_move"]]}', flush=True)
    print(f'[LAYA] Quyết định: {LABELS[result["move"]]}', flush=True)
    print('[LAYA] Xác suất: ' + json.dumps(result['probabilities'], ensure_ascii=False), flush=True)
    print(f'[LAYA] Confidence SDK: {result["confidence"]}; '
          f'inference: {result["inference_seconds"]:.3f} s', flush=True)
    print('[LAYA] Raw output: ' + json.dumps(result['raw'], ensure_ascii=False), flush=True)
    if display_result:
        display_result(result)
    try:
        print(f'[HAND] {hand.port}: thực hiện {result["move"]} ...', flush=True)
        perform_move(hand, result['move'])
        result['completed'] = True
        result['hardware_status'] = ('DRY RUN: đã kiểm tra, không chuyển động.' if hand.dry_run
                                     else 'HOÀN TẤT: servo đạt tư thế; giữ torque.')
        print('[HAND] ' + result['hardware_status'], flush=True)
        if result['outcome']:
            print('[GAME] ' + OUTCOMES[result['outcome']], flush=True)
    except BaseException as exc:
        result['hardware_status'] = f'LỖI CHUYỂN ĐỘNG: {type(exc).__name__}: {exc}'
        print('[HAND] ' + result['hardware_status'], flush=True)
        try:
            hand.release()
        except Exception as release_error:
            print(f'[HAND] Không nhả được toàn bộ torque: {release_error}', flush=True)
        raise
    finally:
        history.append(result)
        if display_result:
            display_result(result)
    return result
