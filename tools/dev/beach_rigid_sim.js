'use strict';
// Shape and joint continuity regression for the published beach cutout rig.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const L = require('../../ui/puppet.js').logic;
const dir = path.resolve(__dirname, '../../docs/design/beach-standing/preview');
const raw = JSON.parse(fs.readFileSync(path.join(dir, 'mascot.json'), 'utf8'));
const rig = L.cleanRig(raw.rig, raw.moods.normal, { base: '' });
assert.ok(rig, 'rig loads');
assert.ok(rig.deformers.every(d => d.type !== 'scale' && d.region === '*' && !d.falloff), 'uniform rigid transforms only');
assert.equal(rig.layers.length, 14);
function dimensions(src) {
  const b = fs.readFileSync(path.join(dir, src));
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
}
function transform(layer, p, point) {
  const g = L.buildGrid(rig, {x:point[0],y:point[1],w:1,h:1}, {cols:1,rows:1,layer});
  return L.deform(g, rig, p).slice(0,2);
}
let edges = 0, joints = 0;
const poses = [L.DEFAULTS,
  {...L.DEFAULTS,bodyX:-1,bodyZ:-.5,angleZ:-.4,breath:1},
  {...L.DEFAULTS,bodyX:1,bodyZ:.5,angleZ:.4,breath:1}];
for (const pose of poses) {
  const p = {...pose}; L.steadyPhysics(rig.physics, p);
  for (const l of rig.layers) {
    const [w,h] = l.src ? dimensions(l.src) : [rig.size.w,rig.size.h];
    const rect = l.src ? {x:l.x,y:l.y,w:w*l.h/h,h:l.h} : {x:0,y:0,w,h};
    const g = L.buildGrid(rig,rect,{cols:4,rows:4,layer:l.id});
    const out = L.deform(g,rig,p);
    for(let i=0;i<g.index.length;i+=3) {
      const triangle = Array.from(g.index.slice(i,i+3));
      for(let j=0;j<3;j++) {
        const a=triangle[j]*2,b=triangle[(j+1)%3]*2;
        const length = values => Math.hypot(values[a]-values[b],values[a+1]-values[b+1]);
        assert.ok(Math.abs(length(out)-length(g.rest))<.001, l.id+': edge length preserved');
        edges++;
      }
    }
    if(l.id==='base') assert.deepEqual(out,g.rest,'feet stay fixed');
  }
  for(const [thigh,calf,knee,ankle] of [
    ['thighL','calfL',[474,1046],[493,1430]],
    ['thighR','calfR',[638,1060],[696,1433]]]) {
    const a=transform(thigh,p,knee),b=transform(calf,p,knee),foot=transform(calf,p,ankle);
    assert.ok(Math.hypot(a[0]-b[0],a[1]-b[1])<.001, 'knee shared by both pieces');
    assert.ok(Math.hypot(foot[0]-ankle[0],foot[1]-ankle[1])<.001,'ankle pivot stays fixed');
    joints+=2;
  }
}
assert.ok(rig.layers.find(l=>l.id==='chest').src, 'chest is a separate drawing');
console.log(JSON.stringify({edge_length_cases:edges,knee_and_ankle_cases:joints,foot_poses:poses.length}));
