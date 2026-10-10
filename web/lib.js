// 纯函数（无 DOM、无网络），供页模块 import，并由 tests/test_web_frontend.py 经 node 直接测。

/** 世界 X → 画布右，世界 Y → 画布上（俯视）；比例 = 画布宽 / (2·extent)。 */
export function worldToCanvas(x, y, ext, w, h) {
  const s = w / (2 * ext);
  return [w / 2 + x * s, h / 2 - y * s];
}

export function canvasToWorld(px, py, ext, w, h) {
  const s = w / (2 * ext);
  return [(px - w / 2) / s, (h / 2 - py) / s];
}

/** 跨镜按 order 顺接同角色路径：{char_id: [[x,y,z], ...]}；无 paths 键的镜跳过、不猜点。 */
export function collectPaths(shotList) {
  const merged = {};
  const ordered = [...shotList].sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  for (const shot of ordered) {
    const paths = shot.paths;
    if (!paths || typeof paths !== "object") continue;
    for (const [cid, pts] of Object.entries(paths)) {
      if (!Array.isArray(pts) || pts.length === 0) continue;
      (merged[cid] = merged[cid] || []).push(...pts);
    }
  }
  return merged;
}

/** 行级 LCS diff：返回 [{op: "eq"|"del"|"add", a?, b?}]。 */
export function lineDiff(aText, bText) {
  const a = aText.split("\n");
  const b = bText.split("\n");
  const n = a.length, m = b.length;
  const t = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      t[i][j] = a[i] === b[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1]);
    }
  }
  const ops = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { ops.push({ op: "eq", a: a[i], b: b[j] }); i++; j++; }
    else if (t[i + 1][j] >= t[i][j + 1]) ops.push({ op: "del", a: a[i++] });
    else ops.push({ op: "add", b: b[j++] });
  }
  while (i < n) ops.push({ op: "del", a: a[i++] });
  while (j < m) ops.push({ op: "add", b: b[j++] });
  return ops;
}

/** 设置页路径读写（"a.b.c"）。缺中间层时 get 返回 undefined。 */
export function getPath(obj, path) {
  return path.split(".").reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), obj);
}

export function setPath(obj, path, value) {
  const keys = path.split(".");
  const last = keys.pop();
  const parent = keys.reduce((o, k) => o[k], obj);
  parent[last] = value;
}

/** 规则开关：返回新的 rules_disabled（排序、去重）。 */
export function toggleDisabled(list, ruleId, enable) {
  const s = new Set(list || []);
  if (enable) s.delete(ruleId); else s.add(ruleId);
  return Array.from(s).sort();
}
