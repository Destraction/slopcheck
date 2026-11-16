// Правила TypeScript, которым нужны типы: промисы без await, async там,
// где ждут обычную функцию, await не-промиса, лишние приведения типов.
// Подключается адаптером eslint-typed, только если зависимости проекта
// установлены: без node_modules типы библиотек превращаются в any, и
// правила дают ложные находки. Загрузка плагинов — в eslint-load.cjs.
const { load, root } = require("./eslint-load.cjs");

const tseslint = load("typescript-eslint");

module.exports = [
  {
    basePath: root,
    files: ["**/*.{ts,tsx,mts,cts}"],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: root,
        ecmaFeatures: { jsx: true },
      },
    },
    linterOptions: { reportUnusedDisableDirectives: "off" },
    plugins: { "@typescript-eslint": tseslint.plugin },
    rules: {
      "@typescript-eslint/no-floating-promises": "warn",
      "@typescript-eslint/no-misused-promises": "warn",
      "@typescript-eslint/await-thenable": "warn",
      "@typescript-eslint/no-unnecessary-type-assertion": "warn",
    },
  },
];
