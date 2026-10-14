"""视线与注意力层五指标的纯 Python demo 实现。样例显著度/节拍映射为样例口径。"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from .composition import SubjectBox
from .evaluation_protocol import (ContentFrame, EvaluationOutput, Finding,
    FrameSample, IntentContract, Measurement, SequenceSample, Severity,
    ShotSample, TargetInterval, Prescription, ProjectedSubject)
from .prescription import validate_prescription
from ..contracts.tools import ACTION_TOOLS

#: demo 头位高度（NDC 画高），照 SPEC B3。
HEAD_UNIT_NDC = 0.10

#: 阈值与边界（照抄注册表口径，样例口径映射放模块内常量）。
GAZE_TARGET = 0.80            # gaze_target_visibility 可见比例目标下界
GAZE_EDGE_EPS = 0.01          # 恰在下界/画面边缘的两可带
EYELINE_BOUND_EPS = 0.05      # 高度差恰 1 个头位边界的两可带
FOCUS_TARGET = 0.75           # focus_competition 竞争比目标上界
FOCUS_BOUND_EPS = 0.03        # 恰在 0.75 边界的两可带
BEAT_TARGET = 0.90            # beat_coverage 覆盖率目标下界
BEAT_BOUND_EPS = 0.02         # 恰在 0.90 边界且元素正入画的两可带
_THIRDS_X = (1.0 / 3.0, 2.0 / 3.0)   # 三分法锚点横坐标（demo 口径）
_THIRDS_Y = (1.0 / 3.0, 2.0 / 3.0)   # 三分法锚点纵坐标（demo 口径）
_ATT_ANCHOR_EPS = 0.10        # 距三分区锚点 ≤0.10 视为位于视觉锚点
_REPAIR = {
 "gaze_target_visibility": ("换侧机位让视线目标回到画内", ("视线目标恢复可见",), ("move_camera",)),
 "eyeline_consistency": ("统一视线锚点高度", ("对切镜头保持互看关系",), ("move_camera",)),
 "attention_priority": ("提高主体视觉权重", ("意图主体重新成为画面重点",), ("move_camera", "reframe")),
 "focus_competition": ("弱化陪衬主体的视觉竞争", ("主次显著度恢复清晰",), ("move_character", "reframe")),
 "beat_coverage": ("延长镜头或补拍动作区", ("节拍元素覆盖完整",), ("move_camera", "reframe")),
}

def _shots_of(s):
    if isinstance(s, ShotSample): return (s,)
    if isinstance(s, SequenceSample): return s.shots
    raise TypeError(type(s))
def _clamp(v): return max(0.0, min(1.0, float(v)))
def _boundary(value, boundary, eps): return abs(float(value)-boundary) <= eps
def _ambiguous_warning(component, boundary_desc, evidence):
    """结构性两可的三态输出：WARNING + 「需人工复核」结尾，不产处方。"""
    return Finding(component, Severity.WARNING, f"{boundary_desc}需人工复核",
                   evidence)
def _measure(metric, raw, target, frames, conf=1.0):
    return Measurement(metric, round(raw,6), round(_clamp(raw if target.min_value is not None else 1-raw),6), target, tuple(frames), conf, "demo")
def _sub(frame, sid): return frame.subject(sid)

def _thirds_distance(cx, cy):
    """主体中心到最近三分区锚点的距离（demo 口径，照 composition._thirds）。"""
    return min(math.hypot(float(cx) - tx, float(cy) - ty)
               for tx in _THIRDS_X for ty in _THIRDS_Y)

def _attention_position_ambiguous(shot, sid):
    """结构性两可：面积维意图主体占优，但主体偏离三分区、陪衬更近视觉锚点，
    意图排序可两解（B3 口径，样例显著度映射放模块常量）。"""
    if not sid:
        return False
    for f in shot.frames:
        hero = _sub(f, sid)
        comps = [s for s in f.subjects
                 if s.subject_id != sid and s.visible_ratio > 0]
        if not hero or not comps:
            continue
        hd = _thirds_distance(hero.box.center_x, hero.box.center_y)
        cd = min(_thirds_distance(s.box.center_x, s.box.center_y)
                 for s in comps)
        if hd > _ATT_ANCHOR_EPS and cd <= _ATT_ANCHOR_EPS:
            return True
    return False

def _gaze(shot, intent):
    frames=shot.frames; target=intent.gaze_target if intent else None
    if not target:
        return _measure("gaze_target_visibility",1.0,TargetInterval(min_value=.8),[f.frame for f in frames],.9), ()
    vals=[]; ev=[]
    edge=False
    for f in frames:
        s=_sub(f,target)
        vals.append((s.visible_ratio if s else 0.0) * (s.box.inside_ratio() if s else 0.0))
        if s and (s.box.left<=.01 or s.box.right>=.99 or s.box.top>=.99 or s.box.bottom<=.01): edge=True
        ev.append(f.frame)
    raw=min(vals) if vals else 0.0; fs=[]
    if raw<=0: fs.append(Finding("gaze_target_visibility",Severity.FATAL,"视线目标完全不在画内",tuple(ev),"H4"))
    elif raw<GAZE_TARGET: fs.append(Finding("gaze_target_visibility",Severity.ERROR,"视线目标被遮挡或可见比例不足",tuple(ev)))
    elif _boundary(raw,GAZE_TARGET,GAZE_EDGE_EPS) or edge:
        fs.append(_ambiguous_warning("gaze_target_visibility","视线目标贴近画面边缘，",tuple(ev)))
    return _measure("gaze_target_visibility",raw,TargetInterval(min_value=GAZE_TARGET),ev,
                    .5 if (_boundary(raw,GAZE_TARGET,GAZE_EDGE_EPS) or edge) else 1.0),tuple(fs)

def _eyeline(sample):
    if not isinstance(sample, SequenceSample):
        return _measure("eyeline_consistency",1.0,TargetInterval(min_value=.8),[f.frame for s in _shots_of(sample) for f in s.frames],.9), ()
    shots=sample.shots; ev=[f.frame for s in shots for f in s.frames]
    if len(shots)<2: return _measure("eyeline_consistency",1.0,TargetInterval(min_value=.8),ev), ()
    a,b=shots[0],shots[1]; fa,fb=a.frames[1],b.frames[1]
    ca=max(fa.subjects,key=lambda s:s.box.height,default=None); cb=max(fb.subjects,key=lambda s:s.box.height,default=None)
    if not ca or not cb: return _measure("eyeline_consistency",1.0,TargetInterval(min_value=.8),ev,.9), ()
    if ca.box.facing*cb.box.facing<0:
        return _measure("eyeline_consistency",0.0,TargetInterval(min_value=.8),ev), (Finding("eyeline_consistency",Severity.FATAL,"互看关系断裂",tuple(ev)),)
    diff=abs(ca.box.center_y-cb.box.center_y)/HEAD_UNIT_NDC
    if diff>1.0+EYELINE_BOUND_EPS:
        return _measure("eyeline_consistency",max(0.0,1.0-diff/3.0),TargetInterval(min_value=.8),ev), (Finding("eyeline_consistency",Severity.ERROR,"视线高度跳变",tuple(ev)),)
    if _boundary(diff,1.0,EYELINE_BOUND_EPS):
        return _measure("eyeline_consistency",1.0,TargetInterval(min_value=.8),ev,.5), (_ambiguous_warning("eyeline_consistency","高度差恰在 1 个头位边界，",tuple(ev)),)
    return _measure("eyeline_consistency",1.0,TargetInterval(min_value=.8),ev), ()

def _saliency(s): return max(0.0, s.box.width*s.box.height)*s.visible_ratio*s.box.inside_ratio()

def _attention(shot,intent):
    ev=[f.frame for f in shot.frames]; sid=intent.subject if intent else ""
    if not sid or not shot.frames:
        return _measure("attention_priority",1.0,TargetInterval(min_value=.8),ev,.9), ()
    ratios=[]; any_comp=False
    for f in shot.frames:
        d={s.subject_id:_saliency(s) for s in f.subjects}
        hero=d.get(sid,0.0); others=[v for k,v in d.items() if k!=sid]
        if others:
            any_comp=True; ratios.append(hero/max(max(others),1e-9))
        else:
            ratios.append(1.0)  # 无竞争者：中性通过，不判「完全压过」
    if not any_comp:
        return _measure("attention_priority",1.0,TargetInterval(min_value=.8),ev,.9), ()
    raw=min(ratios); fs=(); amb=False
    if raw<=0: fs=(Finding("attention_priority",Severity.FATAL,"意图主体被完全压过",tuple(ev)),)
    elif raw<.8: fs=(Finding("attention_priority",Severity.ERROR,"显著度排序错位",tuple(ev)),)
    elif _attention_position_ambiguous(shot,sid):
        amb=True
        fs=(_ambiguous_warning("attention_priority",
                               "面积排序明确但意图主体偏离三分区、陪衬更近视觉锚点，意图排序可两解，",
                               tuple(ev)),)
    return _measure("attention_priority",raw,TargetInterval(min_value=.8),ev,
                    .5 if amb else 1.0),fs

def _focus(shot,intent):
    ev=[f.frame for f in shot.frames]; sid=intent.subject if intent else ""; ratios=[]
    for f in shot.frames:
        hero=_sub(f,sid) if sid else None; hs=_saliency(hero) if hero else 1.0
        others=[_saliency(s) for s in f.subjects if s.subject_id!=sid]; ratios.append((max(others) if others else 0)/max(hs,1e-9))
    raw=min(1.0,max(ratios) if ratios else 0.0); fs=()
    if raw>FOCUS_TARGET: fs=(Finding("focus_competition",Severity.ERROR,"陪衬主体明显抢戏",tuple(ev)),)
    elif _boundary(raw,FOCUS_TARGET,FOCUS_BOUND_EPS):
        fs=(_ambiguous_warning("focus_competition","竞争比例处于边界，",tuple(ev)),)
    return _measure("focus_competition",raw,TargetInterval(max_value=FOCUS_TARGET),ev,
                    .5 if _boundary(raw,FOCUS_TARGET,FOCUS_BOUND_EPS) else 1.0),fs

def _beat(shot,intent):
    ev=[f.frame for f in shot.frames]; sid=intent.subject if intent else ""; raw=1.0
    entering=False
    if intent and intent.beats and sid:
        covered=[]
        for f in shot.frames:
            s=_sub(f,sid); ins=s.box.inside_ratio() if s else 0.0
            covered.append(bool(s and ins>0 and s.visible_ratio>=.8))
            if s and 0<ins<1: entering=True
        raw=sum(covered)/len(shot.frames)
    fs=()
    if raw<=0: fs=(Finding("beat_coverage",Severity.FATAL,"节拍元素完全缺失",tuple(ev)),)
    elif raw<BEAT_TARGET: fs=(Finding("beat_coverage",Severity.ERROR,"节拍元素部分缺失",tuple(ev)),)
    elif entering and raw>=BEAT_TARGET-BEAT_BOUND_EPS:
        fs=(_ambiguous_warning("beat_coverage","节拍元素正入画，",tuple(ev)),)
    return _measure("beat_coverage",raw,TargetInterval(min_value=BEAT_TARGET),ev,.5 if entering else 1.0),fs

def evaluate(sample, intent=None):
    ms=[]; fs=[]
    for shot in _shots_of(sample):
        for worker in (_gaze,_attention,_focus,_beat):
            m,f=worker(shot,intent); ms.append(m); fs.extend(f)
    m,f=_eyeline(sample); ms.append(m); fs.extend(f)
    return EvaluationOutput(_shots_of(sample)[0].shot_id,tuple(ms),tuple(fs),intent)

def build_prescriptions(output):
    out=[]
    for f in output.findings:
        if f.severity not in (Severity.FATAL,Severity.ERROR) or f.component not in _REPAIR: continue
        m=next((x for x in output.measurements if x.metric==f.component),None)
        if not m: continue
        d,e,a=_REPAIR[f.component]; p=Prescription(f.component,f.severity,m.raw_value,m.target,a,d,e)
        if validate_prescription(p)[0]: out.append(p)
    return tuple(out)

def render_report(output,prescriptions):
    lines=[f"镜头 {output.shot_id} 视线与注意力层读数："]
    if output.intent: lines.append(f"- 声明意图：{output.intent.intent or '（未声明）'}")
    for m in output.measurements: lines.append(f"- {m.metric}：原始 {m.raw_value:.3f}，归一化 {m.score:.3f}，目标 {m.target.to_dict()}，证据帧 {m.evidence_frames}，置信度 {m.confidence:.2f}")
    for f in output.findings: lines.append(f"- 失败项：{f.component}[{f.severity.value}] {f.message}，证据帧 {f.evidence_frames}")
    for p in prescriptions: lines.append(f"- 修复方向（{p.component}）：{p.direction}\n  预期影响：{'、'.join(p.expected_effect)}")
    return "\n".join(lines)

@dataclass(frozen=True)
class SampleCase: name:str; sample:object; intent:Optional[IntentContract]; expected:str

def _box(i,l,r,t,b,f=1): return ProjectedSubject(i,SubjectBox(i,l,r,t,b,facing=f),visible_ratio=1.0)
def _shot(i,subs,rng=(1,5),vis=None):
    fr=[]
    for n in (rng[0],(rng[0]+rng[1])//2,rng[1]):
        ss=tuple(subs); fr.append(FrameSample(n,ss,shot_id=i))
    return ShotSample(i,rng,ContentFrame.from_shot(i,rng,fr))

_g=_shot('shot_001',(_box('hero',.2,.5,.9,.3),_box('extra',.6,.8,.8,.4)))
_gaze_bad=_shot('shot_001',(_box('hero',-0.4,-.2,.9,.3),_box('extra',.6,.8,.8,.4)))
_att_bad=_shot('shot_001',(_box('hero',-.4,-.2,.9,.3),_box('extra',.0,1.0,1,.0)))
_focus_bad=_shot('shot_001',(_box('hero',.2,.4,.8,.4),_box('extra',.0,.9,1,.0)))
_beat_bad=_shot('shot_001',(_box('hero',-0.4,-.2,.9,.3),))
_gaze_amb=_shot('shot_001',(_box('hero',.0,.2,.9,.3),_box('extra',.2,.4,.8,.4)))
_att_amb=_shot('shot_001',(_box('hero',.0,.30,.9,.6),_box('extra',.27,.40,.43,.23)))
_focus_amb=_shot('shot_001',(_box('hero',.2,.5,.9,.3),_box('extra',.55,.82,.9,.4)))
_beat_amb=_shot('shot_001',(_box('hero',-.05,.20,.9,.3),))
_s2=_shot('shot_002',(_box('hero',.2,.5,.9,.3,f=-1),),rng=(6,10))
SAMPLES={
 'gaze_target_visibility':{'good':SampleCase('gaze_target_visibility',_g,IntentContract('shot_001',subject='hero',gaze_target='hero'),'good'),'bad':SampleCase('gaze_target_visibility',_gaze_bad,IntentContract('shot_001',subject='hero',gaze_target='hero'),'bad'),'ambiguous':SampleCase('gaze_target_visibility',_gaze_amb,IntentContract('shot_001',subject='hero',gaze_target='hero'),'ambiguous')},
 'eyeline_consistency':{'good':SampleCase('eyeline_consistency',SequenceSample((_g,_shot('shot_002',(_box('hero',.2,.5,.9,.3),),rng=(6,10)))),IntentContract('shot_001',subject='hero',gaze_target='hero'),'good'),'bad':SampleCase('eyeline_consistency',SequenceSample((_g,_s2)),IntentContract('shot_001',subject='hero',gaze_target='hero'),'bad'),'ambiguous':SampleCase('eyeline_consistency',SequenceSample((_g,_shot('shot_002',(_box('hero',.2,.5,.8,.2),),rng=(6,10)))),IntentContract('shot_001',subject='hero',gaze_target='hero'),'ambiguous')},
 'attention_priority':{'good':SampleCase('attention_priority',_g,IntentContract('shot_001',subject='hero',gaze_target='hero'),'good'),'bad':SampleCase('attention_priority',_att_bad,IntentContract('shot_001',subject='hero',gaze_target='hero'),'bad'),'ambiguous':SampleCase('attention_priority',_att_amb,IntentContract('shot_001',subject='hero',gaze_target='hero'),'ambiguous')},
 'focus_competition':{'good':SampleCase('focus_competition',_g,IntentContract('shot_001',subject='hero',gaze_target='hero'),'good'),'bad':SampleCase('focus_competition',_focus_bad,IntentContract('shot_001',subject='hero',gaze_target='hero'),'bad'),'ambiguous':SampleCase('focus_competition',_focus_amb,IntentContract('shot_001',subject='hero',gaze_target='hero'),'ambiguous')},
 'beat_coverage':{'good':SampleCase('beat_coverage',_g,IntentContract('shot_001',subject='hero',gaze_target='hero',beats=('主角入场',)),'good'),'bad':SampleCase('beat_coverage',_beat_bad,IntentContract('shot_001',subject='hero',gaze_target='hero',beats=('主角入场',)),'bad'),'ambiguous':SampleCase('beat_coverage',_beat_amb,IntentContract('shot_001',subject='hero',gaze_target='hero',beats=('主角入场',)),'ambiguous')},
}

__all__=['SampleCase','SAMPLES','evaluate','build_prescriptions','render_report']
