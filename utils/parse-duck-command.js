const WALK_MAX_SECONDS = 10;
const WALK_DEFAULT_SECONDS = 3;

const DUCK_PREFIXES = ['鴨子', '/duck'];

// 關鍵字 → 機器人指令（順序有意義：較長、較具體的放前面）
const RULES = [
  { keywords: ['狀態', 'status'], command: null, status: true },
  { keywords: ['停', 'stop'], command: { action: 'stop' } },
  { keywords: ['放鬆', '休息', '睡覺', 'relax'], command: { action: 'torque', enabled: false } },
  { keywords: ['站好', '起來', '站', 'stand'], command: { action: 'stand' } },
  { keywords: ['點頭', 'nod'], command: { action: 'play', name: 'nod' } },
  { keywords: ['搖頭', 'shake'], command: { action: 'play', name: 'shake' } },
  { keywords: ['張望', '看看', 'look'], command: { action: 'play', name: 'look_around' } },
  { keywords: ['蹲', 'crouch'], command: { action: 'play', name: 'crouch' } },
  { keywords: ['開心', 'happy'], command: { action: 'play', name: 'happy' } },
  { keywords: ['跳舞', 'dance'], command: { action: 'play', name: 'dance' } },
  { keywords: ['左轉', 'left turn'], walk: { wz: 0.8 } },
  { keywords: ['右轉', 'right turn'], walk: { wz: -0.8 } },
  { keywords: ['左移', '往左'], walk: { vy: 0.15 } },
  { keywords: ['右移', '往右'], walk: { vy: -0.15 } },
  { keywords: ['後退', '往後', 'back'], walk: { vx: -0.1 } },
  { keywords: ['前進', '往前', '走', 'forward'], walk: { vx: 0.15 } },
];

/**
 * @param {string} text
 * @returns {boolean}
 */
const isDuckCommand = (text) => DUCK_PREFIXES.some((p) => text.toLowerCase().startsWith(p));

/**
 * 把「鴨子 前進 5 秒」這類文字轉成機器人 HTTP API 的指令。
 * @param {string} text
 * @returns {{ command: object|null, status: boolean } | null} 看不懂就回傳 null
 */
const parseDuckCommand = (text) => {
  const prefix = DUCK_PREFIXES.find((p) => text.toLowerCase().startsWith(p));
  const body = (prefix ? text.slice(prefix.length) : text).trim().toLowerCase();
  const rule = RULES.find(({ keywords }) => keywords.some((k) => body.includes(k)));
  if (!rule) return null;
  if (rule.status) return { command: null, status: true };
  if (rule.command) return { command: { ...rule.command }, status: false };
  const seconds = Number((body.match(/(\d+(?:\.\d+)?)\s*(秒|s)/) || [])[1]) || WALK_DEFAULT_SECONDS;
  return {
    command: {
      action: 'walk',
      vx: 0,
      vy: 0,
      wz: 0,
      ...rule.walk,
      duration: Math.min(seconds, WALK_MAX_SECONDS),
    },
    status: false,
  };
};

export { isDuckCommand, parseDuckCommand };
