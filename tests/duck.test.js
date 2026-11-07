import http from 'http';
import {
  afterAll, beforeAll, expect, test,
} from '@jest/globals';
import { isDuckCommand, parseDuckCommand } from '../utils/parse-duck-command.js';

test('isDuckCommand', () => {
  expect(isDuckCommand('鴨子 前進')).toBe(true);
  expect(isDuckCommand('/duck dance')).toBe(true);
  expect(isDuckCommand('我想養鴨子')).toBe(false);
});

test('parseDuckCommand walk with seconds', () => {
  expect(parseDuckCommand('鴨子 前進 5 秒').command).toEqual({
    action: 'walk', vx: 0.15, vy: 0, wz: 0, duration: 5,
  });
  expect(parseDuckCommand('鴨子 左轉').command).toMatchObject({ wz: 0.8, duration: 3 });
  expect(parseDuckCommand('鴨子 往左走').command).toMatchObject({ vy: 0.15 });
  expect(parseDuckCommand('鴨子 前進 60 秒').command.duration).toBe(10);
});

test('parseDuckCommand actions', () => {
  expect(parseDuckCommand('鴨子 跳舞').command).toEqual({ action: 'play', name: 'dance' });
  expect(parseDuckCommand('鴨子 停').command).toEqual({ action: 'stop' });
  expect(parseDuckCommand('鴨子 站好').command).toEqual({ action: 'stand' });
  expect(parseDuckCommand('鴨子 放鬆').command).toEqual({ action: 'torque', enabled: false });
  expect(parseDuckCommand('鴨子 狀態')).toEqual({ command: null, status: true });
  expect(parseDuckCommand('鴨子 唱歌')).toBeNull();
});

let server;
const received = [];

beforeAll(async () => {
  server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => { body += c; });
    req.on('end', () => {
      received.push({
        method: req.method, url: req.url, auth: req.headers.authorization, body,
      });
      const cmd = body ? JSON.parse(body) : {};
      res.setHeader('Content-Type', 'application/json');
      if (cmd.action === 'play' && cmd.name === 'dance') {
        res.statusCode = 400;
        return res.end(JSON.stringify({ error: '目前是 fallen 狀態，請先送 stand' }));
      }
      return res.end(JSON.stringify({
        mode: cmd.action === 'walk' ? 'walk' : 'stand', animation: null, tilt_deg: 7.3, last_error: null,
      }));
    });
  });
  await new Promise((resolve) => { server.listen(0, '127.0.0.1', resolve); });
  process.env.DUCK_API_URL = `http://127.0.0.1:${server.address().port}`;
  process.env.DUCK_API_TOKEN = 'secret';
});

afterAll(() => server.close());

const fakeContext = (text) => ({
  trimmedText: text,
  texts: [],
  pushText(s) { this.texts.push(s); return this; },
  pushError(e) { this.texts.push(`ERR ${e.message}`); return this; },
});

test('duck handler talks to robot API', async () => {
  const { default: duckHandler } = await import('../app/handlers/duck.js');
  expect(duckHandler(fakeContext('你好'))).toBe(false);

  const walk = await duckHandler(fakeContext('鴨子 前進'));
  expect(walk.texts[0]).toContain('walk');
  expect(received.at(-1)).toMatchObject({ method: 'POST', url: '/command', auth: 'Bearer secret' });
  expect(JSON.parse(received.at(-1).body)).toMatchObject({ action: 'walk', vx: 0.15 });

  const status = await duckHandler(fakeContext('鴨子 狀態'));
  expect(received.at(-1)).toMatchObject({ method: 'GET', url: '/status' });
  expect(status.texts[0]).toContain('stand');

  const refused = await duckHandler(fakeContext('鴨子 跳舞'));
  expect(refused.texts[0]).toContain('請先送 stand');

  const help = await duckHandler(fakeContext('鴨子 唱歌'));
  expect(help.texts[0]).toContain('聽不懂');
});
