from pathlib import Path
import os
os.environ['KERAS_BACKEND']='torch'
os.environ['USE_TF']='0'
import sys,time,json,urllib.request,zipfile,io
import numpy as np
import cv2
import torch
import nbformat
from PIL import Image
from unittest.mock import patch
sys.path.insert(0,str(Path('PythonExample').resolve()))
import AmazingHand_RPSGame as r
torch.set_num_threads(4)
archive=Path('.tools/rps-test-set.zip')
if not archive.exists():
    print('Tải test set chính thức TensorFlow...',flush=True)
    urllib.request.urlretrieve('https://storage.googleapis.com/download.tensorflow.org/data/rps-test-set.zip',archive)
config=r.GameConfig()
session=r.RPSModelSession('models/rps.h5',config)
samples=[]
correct=0
accepted=0
accepted_correct=0
best={}
latencies=[]
with zipfile.ZipFile(archive) as bundle:
    for name in sorted(bundle.namelist()):
        if not name.endswith('.png'):
            continue
        label=Path(name).parent.name
        if label not in r.MOVES:
            continue
        rgb=np.array(Image.open(io.BytesIO(bundle.read(name))).convert('RGB'))
        batch=np.array(Image.fromarray(rgb).resize((150,150),Image.Resampling.NEAREST),dtype=np.float32)[None]/255
        started=time.perf_counter()
        probs=session.infer(batch)
        latencies.append((time.perf_counter()-started)*1000)
        prediction=config.rps_class_names[int(probs.argmax())]
        ok=prediction==label
        correct+=ok
        confident=probs.max()>=config.confidence_threshold and np.sort(probs)[-1]-np.sort(probs)[-2]>=config.prediction_margin
        accepted+=int(confident)
        accepted_correct+=int(confident and ok)
        if ok and confident and (label not in best or probs.max()>best[label][0]):
            best[label]=(float(probs.max()),rgb)
        samples.append(label)
report={'dataset':'TensorFlow RPS test split', 'images':len(samples),'correct':int(correct),
        'accuracy':correct/len(samples),'accepted':accepted,'accepted_correct':accepted_correct,
        'latency_mean_ms':float(np.mean(latencies)), 'latency_p95_ms':float(np.percentile(latencies,95))}
print('EVALUATION',json.dumps(report),flush=True)
session.close()
assert set(best)==set(r.MOVES),best.keys()

class ReplayCamera:
    def __init__(self,cfg):
        self.config=cfg; self.closed=True; self.sequence=0
    def open(self):
        self.closed=False
        return self
    def get_frame(self,**kwargs):
        self.sequence+=1
        game=ns.get('game')
        index=len(game.history) if hasattr(game,'history') else 0
        move=r.MOVES[index%3]
        image=cv2.cvtColor(best[move][1],cv2.COLOR_RGB2BGR)
        frame=np.full((720,1280,3),255,np.uint8)
        a,b,c,d=self.config.roi
        x1,y1,x2,y2=int(a*1280),int(b*720),int(c*1280),int(d*720)
        frame[y1:y2,x1:x2]=cv2.resize(image,(x2-x1,y2-y1),interpolation=cv2.INTER_NEAREST)
        return frame,time.monotonic(),self.sequence
    def close(self): self.closed=True

notebook=nbformat.read('amazinghand_rps_game.ipynb',4)
ns={'__name__':'__main__'}
try:
    for index,cell in enumerate(c for c in notebook.cells if c.cell_type=='code'):
        source = cell.source.replace('ROBOT_ENABLED = True', 'ROBOT_ENABLED = False') if index == 1 else cell.source
        if index==3:
            ns['config'].robot_enabled=False
            ns['config'].preview_seconds=0
            ns['config'].countdown_seconds=.01
            ns['config'].result_seconds=0
            ns['config'].gesture_timeout_seconds=1
            ns['config'].log_path='.tools/h5-pipeline-rounds.jsonl'
        with patch('rustypot.Scs0009PyController',side_effect=AssertionError('Không được mở serial khi test mô phỏng')):
            if index==3:
                with patch.object(r,'CameraStream',ReplayCamera):
                    exec(compile(cell.source,f'Cell{index+1}','exec'),ns)
            elif index==8:
                with patch.object(ns['game'].display,'show'),patch.object(ns['game'].display,'wait_action',side_effect=lambda game, record, finished: 'quit' if finished else 'start'), patch.object(ns['game'].display,'confirm_move',side_effect=lambda game, record: r.MOVES[len(game.history)%3]):
                    exec(compile(cell.source,'Cell9','exec'),ns)
            else:
                exec(compile(source,f'Cell{index+1}','exec'),ns)
        print(f'PASS notebook Cell {index+1}',flush=True)
    game=ns['game']
    assert max(game.scoreboard['human'],game.scoreboard['robot'])==3 and all(x['valid'] and x['human_confirmed'] for x in game.history)
    assert all(x['recognition_mode']=='single_snapshot' and
               x['gesture_diagnostics']['frames']==1 and Path(x['snapshot_path']).is_file()
               for x in game.history)
    assert [x['human_move'] for x in game.history]==[r.MOVES[i%3] for i in range(len(game.history))]
    model_id=id(ns['recognizer_session'].model)
    agent_id=id(ns['decision_engine'].agent)
    with patch.object(game.display,'show'),patch.object(game.display,'wait_action',side_effect=lambda game, record, finished: 'quit' if finished else 'start'), patch.object(game.display,'confirm_move',side_effect=lambda game, record: r.MOVES[len(game.history)%3]):
        exec(compile(notebook.cells[-1].source,'Cell9-repeat','exec'),ns)
    assert max(game.scoreboard['human'],game.scoreboard['robot'])==3
    assert id(ns['recognizer_session'].model)==model_id
    assert id(ns['decision_engine'].agent)==agent_id
    report['notebook_cells_passed']=9
    report['matches_passed']=2
    report['recognition_mode']='single_snapshot: one saved frame and one classification per round'
    report['robot']='simulated; serial constructor forbidden'
    report['camera']='replay of labeled images; webcam probe printed separately'
    print('PASS: 2 trận chạm 3 thắng, xác nhận người chơi, H5 + Laya thật; không reload model, không mở serial.',flush=True)
finally:
    if 'close_session' in ns: ns['close_session']()
Path('logs').mkdir(exist_ok=True)
Path('logs/rps_h5_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
