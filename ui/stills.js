/* AI 스튜디오 — 직원 정지 그림 (직원 상태창·꾸미기 미리보기·회의실)
 *
 * 직원의 그림 띠 목록을 읽어 두고(Stills.init·reload), 꾸미기대로 칠한 한 동작의 정지 그림을 만든다(Stills.still).
 * 띠는 tools/sprites/make_strips.gd가 만든 가로 띠(<직원>.<동작>.strip.png)이고, 색·몸 조절은 looks.js가 한다.
 * 옛 도트 사무실(직원이 걷는 본사 화면)은 CEO 결정 2026-10-06으로 완전히 없앴다 — 이 파일에는 그 장면이 없다.
 */
'use strict';

const Stills = (() => {
  // 그림 목록은 배포 것과 설치한 것(data/assets)을 합쳐 읽는다 (Looks.loadIndex)
  async function init() {
    await Looks.init(await Looks.loadIndex());
  }

  // 의상실에서 새 옷이 설치되면 그림 목록을 다시 읽는다 (app.js가 look_options.version이 바뀌면 부른다)
  async function reload() {
    const next = await Looks.loadIndex();
    if (!next) return; // 못 읽었으면 지금 목록을 그대로 둔다
    await Looks.init(next);
  }

  // 한 동작을 꾸미기대로 그린 정지 그림 (회의실·꾸미기 미리보기). 그림이 아직이면 준비되는 대로 다시 그린다.
  function still(id, action, look, height) {
    const c = document.createElement('canvas');
    c.className = 'sprite-still';
    const paint = () => {
      const { meta, image } = Looks.strip(id, action, look, paint);
      if (!meta || !image) return;
      // 배율은 몸 조절 전 높이로 정한다: 키·머리를 키운 만큼 미리보기도 커 보여야 한다 (meta.grown = 늘어난 높이)
      const s = height / (meta.frameHeight - (meta.grown || 0));
      c.width = Math.round(meta.frameWidth * s);
      c.height = Math.round(meta.frameHeight * s);
      const ctx = c.getContext('2d');
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(image, 0, 0, meta.frameWidth, meta.frameHeight, 0, 0, c.width, c.height);
    };
    paint();
    return c;
  }

  return { init, reload, still };
})();
