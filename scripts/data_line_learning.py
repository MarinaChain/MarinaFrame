#!/usr/bin/env python3
"""Small CPU experiment: classify an ink-centred patch as grid or contour.

Labels come from procedural rendering layers, never an expert or a source CAD
reference. The query locations are supplied, so this does not discover contours,
calibrate a drawing or reconstruct a hull. No authentic image enters training.
"""
from __future__ import annotations

import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
os.environ.setdefault('OMP_NUM_THREADS', '2')

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

VERSION = 'marinaframe-procedural-ink-learning-1'
FAMILIES = {'development': ['round', 'chine', 'flare', 'bulb'],
            'validation': ['double_chine'], 'sealed_procedural_test': ['tumblehome']}
PROTOCOL = {
    'schema_version': VERSION,
    'task': 'binary classification at a supplied ink location: grid=0 versus contour=1',
    'label_origin': 'known procedural rendering layers; not expert annotations or real source gold',
    'input': 'two 17x17 grayscale patches, original radius8 and radius24 downsampled; no coordinates, vessel IDs, family IDs or render masks',
    'families_by_split': FAMILIES,
    'panels_per_family': 36, 'queries_per_class_per_panel': 24,
    'development_seed': 47001, 'validation_seed': 58001, 'test_seed': 79001,
    'weight_seed': 2803, 'hidden_units': 32, 'epochs': 80, 'batch_size': 128,
    'learning_rate': 0.025, 'weight_decay': 0.0003,
    'baseline': 'axis-aligned ink support heuristic; threshold selected only on validation from a predeclared grid',
    'baseline_thresholds': [0.05,0.10,0.15,0.20,0.25,0.30,0.35,0.40,0.45,0.50,0.55,0.60,0.65,0.70,0.75,0.80,0.85,0.90,0.95,0.99,1.01],
    'selection': 'MLP checkpoint with lowest validation cross entropy; final procedural test evaluated once after selection',
    'test_is_independent_engineering_truth': False,
    'methodology_revision': 'Run1 retained; baseline search expanded because its validation optimum hit the old grid boundary. New tumblehome family replaces previously observed reverse_flare test. Same-author procedural limitations remain.',
    'engineering_approved': False,
    'scope_limits': ['Query locations are supplied from renderer masks.',
                     'All panels are authored by this experiment; withheld families are not an independent external benchmark.',
                     'Overlaps and points within 3px of another class are excluded; cluttered intersections are not proven.',
                     'Neither contour tracing, station interpretation, calibration, CAD validity nor hull accuracy is evaluated.',
                     'No real-drawing labels, qualified human labels, external model endpoint or base-model fine-tuning is used.',
                     'A successful experiment does not authorize automatic contour selection in the production harness.'],
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def render_panel(family, seed):
    rng = np.random.default_rng(seed)
    size = 160
    masks = [Image.new('L', (size,size), 0), Image.new('L', (size,size), 0)]
    draws = [ImageDraw.Draw(im) for im in masks]
    grid_width = int(rng.integers(1, 3))
    curve_width = int(rng.integers(1, 3))
    gap = int(rng.integers(18, 33))
    offset = int(rng.integers(4, gap))
    for pos in range(offset, size, gap):
        draws[0].line([(pos,0),(pos,size-1)], fill=255, width=grid_width)
        draws[0].line([(0,pos),(size-1,pos)], fill=255, width=grid_width)
    exponent = rng.uniform(0.7,1.9)
    for n in range(5):
        t = np.linspace(0,1,101)
        if family == 'round': f = np.sin(t*np.pi/2)**exponent
        elif family == 'chine': f = np.where(t<0.4, t*0.6, 0.24+(t-0.4)*1.2667)
        elif family == 'flare': f = t**exponent + 0.1*np.sin(t*np.pi*2)
        elif family == 'bulb': f = t + 0.20*np.sin(t*np.pi*2)*(1-t)
        elif family == 'double_chine': f = np.interp(t,[0,.3,.7,1],[0,.15,.75,1])
        elif family == 'reverse_flare': f = t**(1/exponent) + 0.16*np.sin(t*np.pi*1.5)
        elif family == 'tumblehome': f = t + 0.45*np.sin(t*np.pi)
        else: raise ValueError('Unknown family')
        x = 22 + (20+n*22)*f
        y = 144 - t*(78+n*13)
        points = np.stack([x,y],axis=1)
        if rng.random()<0.5: points[:,0] = size-1-points[:,0]
        points += rng.uniform(-4,4,size=2)
        draws[1].line([tuple(p) for p in points], fill=255, width=curve_width)
    # Nuisances are independent of class: either grid or contour may be faint.
    inks = rng.uniform(0.26,0.86,size=2)
    background = np.ones((size,size),dtype=np.float64)*rng.uniform(.86,.99)
    gradient = np.linspace(-.035,.035,size)[None,:]*rng.uniform(-1,1)
    arrays = [np.asarray(m,dtype=np.float64)/255 for m in masks]
    darkness = np.maximum(arrays[0]*inks[0], arrays[1]*inks[1])
    pixels = np.clip(background+gradient-darkness+rng.normal(0,.012,(size,size)),0,1)
    raster = Image.fromarray((pixels*255).astype(np.uint8))
    if rng.random()<0.5: raster = raster.filter(ImageFilter.GaussianBlur(float(rng.uniform(.15,.55))))
    # Candidate coordinates are assisted, but the model receives only pixels.
    candidates=[]
    for label in (0,1):
        other=np.asarray(masks[1-label].filter(ImageFilter.MaxFilter(7)))>0
        valid=(arrays[label]>0)&~other
        valid[:26,:]=False; valid[-26:,:]=False; valid[:,:26]=False; valid[:,-26:]=False
        yy,xx=np.where(valid)
        if len(xx)<PROTOCOL['queries_per_class_per_panel']:
            raise ValueError('Generated panel has too few isolated labelled ink points')
        picked=rng.choice(len(xx),PROTOCOL['queries_per_class_per_panel'],replace=False)
        for index in picked: candidates.append((int(xx[index]),int(yy[index]),label))
    return raster, candidates


def features(raster, points):
    rows=[]
    for x,y,_ in points:
        patches=[]
        for radius in (8,24):
            patch=raster.crop((x-radius,y-radius,x+radius+1,y+radius+1)).resize((17,17),Image.Resampling.BILINEAR)
            a=1-np.asarray(patch,dtype=np.float64)/255
            # Normalize local background only, leaving class-independent contrast.
            a=np.maximum(a-np.quantile(a,.10),0)
            patches.append(a.reshape(-1))
        rows.append(np.concatenate(patches))
    return np.asarray(rows,dtype=np.float64)


def make_split(root, name, seed):
    rows=[]; targets=[]; examples=[]; manifest=[]
    folder=root/'procedural_images'/name; folder.mkdir(parents=True)
    for fi,family in enumerate(FAMILIES[name]):
        for n in range(PROTOCOL['panels_per_family']):
            panel_seed=seed+fi*1000+n
            raster,points=render_panel(family,panel_seed)
            panel_id=f'{family}-{panel_seed}'
            path=folder/f'{panel_id}.png'; raster.save(path)
            rows.extend(features(raster,points)); targets.extend(label for _,_,label in points)
            manifest.append({'panel_id':panel_id,'design_group_id':panel_id,'family':family,'split':name,
                             'seed':panel_seed,'file':str(path.relative_to(root)),'sha256':sha(path),'queries':points})
            if n==0: examples.append((raster.copy(),points,family))
    return np.asarray(rows),np.asarray(targets,dtype=np.int64),manifest,examples


def probabilities(x, model):
    h=np.tanh(x@model['w1']+model['b1'])
    logits=h@model['w2']+model['b2']; logits-=logits.max(axis=1,keepdims=True)
    ex=np.exp(logits); return ex/ex.sum(axis=1,keepdims=True),h


def loss(x,y,model):
    p,_=probabilities(x,model)
    return float(-np.log(np.maximum(p[np.arange(len(y)),y],1e-12)).mean())


def score(y,pred):
    cm=np.zeros((2,2),dtype=int)
    for truth,guess in zip(y,pred): cm[truth,guess]+=1
    recall=np.diag(cm)/np.maximum(cm.sum(axis=1),1)
    precision=np.diag(cm)/np.maximum(cm.sum(axis=0),1)
    f1=2*precision*recall/np.maximum(precision+recall,1e-12)
    return {'examples':int(len(y)),'accuracy':float((y==pred).mean()),
            'balanced_accuracy':float(recall.mean()),'macro_f1':float(f1.mean()),
            'recall_grid':float(recall[0]),'recall_contour':float(recall[1]),
            'confusion_matrix_true_rows_grid_contour':cm.tolist()}


def baseline_support(x):
    patches=x[:,:289].reshape(-1,17,17)
    # The best two-pixel axis strip through the supplied ink point.
    h=patches[:,7:10,:].max(axis=1).mean(axis=1)
    v=patches[:,:,7:10].max(axis=2).mean(axis=1)
    contrast=patches.max(axis=(1,2))
    return np.maximum(h,v)/np.maximum(contrast,.01)


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    start=time.monotonic()
    # Persist specification and hash before generating data or training.
    save_json(out/'protocol.json',PROTOCOL)
    protocol_hash=sha(out/'protocol.json')
    x,y,dev,examples=make_split(out,'development',PROTOCOL['development_seed'])
    vx,vy,val,vexamples=make_split(out,'validation',PROTOCOL['validation_seed'])
    save_json(out/'development-validation-manifest.json',{'development':dev,'validation':val})
    mean=x.mean(axis=0); scale=np.maximum(x.std(axis=0),.03)
    xn=(x-mean)/scale; vn=(vx-mean)/scale
    rng=np.random.default_rng(PROTOCOL['weight_seed'])
    model={'w1':rng.normal(0,.07,(xn.shape[1],32)), 'b1':np.zeros(32),
           'w2':rng.normal(0,.10,(32,2)), 'b2':np.zeros(2)}
    initial={key:a.copy() for key,a in model.items()}
    history=[]; best=None; best_loss=float('inf'); best_epoch=0
    support=baseline_support(vx)
    threshold_scores=[(score(vy,(support<t).astype(int))['balanced_accuracy'],t) for t in PROTOCOL['baseline_thresholds']]
    baseline_threshold=max(threshold_scores,key=lambda pair:(pair[0],-pair[1]))[1]
    initial_loss=loss(xn,y,model)
    updates=0
    for epoch in range(PROTOCOL['epochs']):
        order=rng.permutation(len(y))
        for start_index in range(0,len(y),PROTOCOL['batch_size']):
            idx=order[start_index:start_index+PROTOCOL['batch_size']]
            batch=xn[idx]; truth=y[idx]
            p,h=probabilities(batch,model); p[np.arange(len(idx)),truth]-=1; p/=len(idx)
            dw2=h.T@p+PROTOCOL['weight_decay']*model['w2']; db2=p.sum(axis=0)
            dh=(p@model['w2'].T)*(1-h*h)
            dw1=batch.T@dh+PROTOCOL['weight_decay']*model['w1']; db1=dh.sum(axis=0)
            for key,grad in [('w1',dw1),('b1',db1),('w2',dw2),('b2',db2)]:
                model[key]-=PROTOCOL['learning_rate']*grad
            updates+=1
        validation_loss=loss(vn,vy,model)
        history.append({'epoch':epoch+1,'training_loss':loss(xn,y,model),'validation_loss':validation_loss})
        if validation_loss<best_loss:
            best_loss=validation_loss; best_epoch=epoch+1
            best={key:a.copy() for key,a in model.items()}
    np.savez_compressed(out/'initial_weights.npz',**initial,mean=mean,scale=scale)
    np.savez_compressed(out/'selected_weights.npz',**best,mean=mean,scale=scale)
    save_json(out/'training-history.json',history)
    save_json(out/'selection-frozen-before-test.json',{'protocol_sha256':protocol_hash,'selected_epoch':best_epoch,
              'weights_sha256':sha(out/'selected_weights.npz'),'baseline_threshold':baseline_threshold,
              'selection_source':'validation only','test_read_before_selection':False,
              'baseline_validation_grid':[{'balanced_accuracy':accuracy,'threshold':threshold} for accuracy,threshold in threshold_scores]})
    # No test pixels or labels are created/read until checkpoint and threshold are fixed.
    tx,ty,test,texamples=make_split(out,'sealed_procedural_test',PROTOCOL['test_seed'])
    save_json(out/'test-manifest.json',{'test':test,'evaluation_count':1})
    tn=(tx-mean)/scale
    learned=np.argmax(probabilities(tn,best)[0],axis=1)
    simple=(baseline_support(tx)<baseline_threshold).astype(int)
    save_json(out/'test-predictions.json',{'true':ty.tolist(),'baseline':simple.tolist(),'learned':learned.tolist(),
              'ordering':'test manifest panels in order, queries in recorded order; no predictions fed back to training'})
    # Confidence interval is clustered by panel; query pixels are not independent.
    rng_boot=np.random.default_rng(909)
    block=PROTOCOL['queries_per_class_per_panel']*2
    differences=((learned==ty).astype(float)-(simple==ty).astype(float)).reshape(-1,block).mean(axis=1)
    boot=np.array([rng_boot.choice(differences,len(differences),replace=True).mean() for _ in range(2000)])
    report={'schema_version':VERSION,'created_utc':datetime.now(timezone.utc).isoformat(),
            'protocol_sha256':protocol_hash,'training_script_sha256':sha(__file__),
            'real_source_training_images':0,'real_source_gold_labels':0,'external_provider_calls':0,
            'panels':{'development':len(dev),'validation':len(val),'test':len(test)},
            'queries':{'development':len(y),'validation':len(vy),'test':len(ty)},
            'trainable_parameters':sum(a.size for a in model.values()),'gradient_updates':updates,
            'initial_training_loss':initial_loss,'selected_training_loss':loss(xn,y,best),
            'selected_epoch':best_epoch,'selected_validation_loss':best_loss,
            'weights_l2_change':float(np.sqrt(sum(np.square(best[k]-initial[k]).sum() for k in best))),
            'initial_weights_sha256':sha(out/'initial_weights.npz'),'selected_weights_sha256':sha(out/'selected_weights.npz'),
            'baseline_threshold':baseline_threshold,'test_evaluations':1,
            'baseline_test':score(ty,simple),'learned_test':score(ty,learned),
            'accuracy_difference_panel_bootstrap_95pct':np.quantile(boot,[.025,.975]).tolist(),
            'validation_learned':score(vy,np.argmax(probabilities(vn,best)[0],axis=1)),
            'independent_real_drawing_accuracy_proven':False,'engineering_approved':False,
            'production_enabled':False,'limitations':PROTOCOL['scope_limits'],
            'wall_seconds':time.monotonic()-start}
    report['experiment_outcome']='procedural_advantage_observed' if report['learned_test']['balanced_accuracy']>report['baseline_test']['balanced_accuracy'] else 'no_advantage_observed_preserved'
    save_json(out/'results.json',report)
    # A labelled rendered sheet for actual visual inspection, never source ground truth.
    samples=examples+vexamples+texamples
    board=Image.new('RGB',(3*320,2*355),'white'); draw=ImageDraw.Draw(board)
    for n,(im,points,family) in enumerate(samples):
        im=im.convert('RGB').resize((320,320),Image.Resampling.NEAREST)
        local=ImageDraw.Draw(im)
        for px,py,label in points[::4]:
            colour=(210,30,55) if label else (0,135,170)
            local.ellipse((px*2-3,py*2-3,px*2+3,py*2+3),outline=colour,width=2)
        xx=(n%3)*320; yy=(n//3)*355; board.paste(im,(xx,yy)); draw.text((xx+8,yy+325),family+' | red: contour; teal: grid',fill='black')
    board.save(out/'procedural-label-contact-sheet.png')
    print(json.dumps(report,indent=2))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    run(args.out)

if __name__=='__main__': main()
