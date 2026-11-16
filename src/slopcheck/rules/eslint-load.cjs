// Общее для конфигов ESLint slopcheck (eslint.config.cjs, eslint.typed.cjs).
//
// Конфиги лежат в пакете slopcheck, а не в проверяемом репозитории, поэтому:
//   - плагины грузятся из глобального node_modules (SLOPCHECK_NODE_MODULES,
//     `npm root -g`): обычный require искал бы их рядом с этим файлом;
//   - root = SLOPCHECK_ROOT идёт в basePath: без него ESLint 9 считает файлы
//     вне каталога конфига «вне base path» и молча их пропускает.
const path = require("node:path");
const { createRequire } = require("node:module");

const modulesDir = process.env.SLOPCHECK_NODE_MODULES;

module.exports = {
  load: modulesDir ? createRequire(path.join(modulesDir, "_slopcheck.js")) : require,
  root: process.env.SLOPCHECK_ROOT || process.cwd(),
};
