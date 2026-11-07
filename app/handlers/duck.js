import axios from 'axios';
import config from '../../config/index.js';
import { t } from '../../locales/index.js';
import { isDuckCommand, parseDuckCommand } from '../../utils/parse-duck-command.js';
import Context from '../context.js';

/**
 * @param {Context} context
 * @returns {boolean}
 */
const check = (context) => isDuckCommand(context.trimmedText);

const client = () => axios.create({
  baseURL: config.DUCK_API_URL,
  timeout: config.DUCK_TIMEOUT,
  headers: config.DUCK_API_TOKEN ? { Authorization: `Bearer ${config.DUCK_API_TOKEN}` } : {},
});

const describe = (status) => t('__DUCK_STATUS')(status);

/**
 * 在 LINE 輸入「鴨子 前進」「鴨子 跳舞」等，轉成機器人 HTTP API 指令。
 * @param {Context} context
 * @returns {Promise<Context>}
 */
const exec = (context) => check(context) && (
  async () => {
    if (!config.DUCK_API_URL) return context.pushText(t('__ERROR_MISSING_ENV')('DUCK_API_URL'));
    const parsed = parseDuckCommand(context.trimmedText);
    if (!parsed) return context.pushText(t('__DUCK_HELP'));
    try {
      const { data } = parsed.status
        ? await client().get('/status')
        : await client().post('/command', parsed.command);
      context.pushText(describe(data));
    } catch (err) {
      const reason = err.response?.data?.error;
      if (reason) return context.pushText(t('__DUCK_ERROR')(reason));
      context.pushError(err);
    }
    return context;
  }
)();

export default exec;
