// Правила TypeScript, которым нужны типы: промисы без await, async там,
// где ждут обычную функцию, await не-промиса, лишние приведения типов.
// Подключается адаптером eslint-typed, только если зависимости проекта
// установлены: без node_modules типы библиотек превращаются в any, и
// правила дают ложные находки. Загрузка плагинов — в eslint-load.cjs.
const { load, root } = require("./eslint-load.cjs");

const tseslint = load("typescript-eslint");

// act() из React 19 всегда возвращает thenable, даже для синхронного колбэка:
// `act(() => vi.advanceTimersByTime(300))` в тестах — не потерянный промис.
const safeAct = ["@testing-library/react", "react", "react-dom/test-utils"].map((pkg) => ({
  from: "package",
  name: "act",
  package: pkg,
}));

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
      "@typescript-eslint/no-floating-promises": ["warn", { allowForKnownSafeCalls: safeAct }],
      // async-обработчик в JSX-атрибуте (`onSubmit={handleSubmit}`) — идиома React:
      // ошибки обработчик ловит сам. Проверка аргументов и свойств остаётся.
      "@typescript-eslint/no-misused-promises": ["warn", { checksVoidReturn: { attributes: false } }],
      "@typescript-eslint/await-thenable": "warn",
      "@typescript-eslint/no-unnecessary-type-assertion": "warn",
    },
  },
];
