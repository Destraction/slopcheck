// Конфиг ESLint для slopcheck: React/TS-смеллы, мёртвый код, JSDoc экспортов.
// Загрузка плагинов и корень анализа — в eslint-load.cjs.
// Все правила — "warn": категорию и severity находки задаёт адаптер.
const { load, root } = require("./eslint-load.cjs");

const tseslint = load("typescript-eslint");
const react = load("eslint-plugin-react");
const reactHooks = load("eslint-plugin-react-hooks");
const jsdoc = load("eslint-plugin-jsdoc");

module.exports = [
  {
    basePath: root,
    files: ["**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}"],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: { ecmaFeatures: { jsx: true }, sourceType: "module" },
    },
    linterOptions: { reportUnusedDisableDirectives: "off" },
    settings: { react: { version: "19.0" } },
    plugins: {
      "@typescript-eslint": tseslint.plugin,
      react,
      "react-hooks": reactHooks,
      jsdoc,
    },
    rules: {
      "no-empty": "warn",
      "no-useless-catch": "warn",
      "no-unreachable": "warn",
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/ban-ts-comment": "warn",
      "@typescript-eslint/no-non-null-assertion": "warn",
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", ignoreRestSiblings: true },
      ],
      "react-hooks/rules-of-hooks": "warn",
      "react-hooks/exhaustive-deps": "warn",
      "react-hooks/set-state-in-effect": "warn",
      "react/jsx-key": "warn",
      "react/no-array-index-key": "warn",
      "react/no-danger": "warn",
      // Рендер-функция в пропе (`Cell()`, `components={{...}}`) — не компонент внутри рендера.
      "react/no-unstable-nested-components": ["warn", { allowAsProps: true }],
      "jsdoc/require-jsdoc": [
        "warn",
        {
          publicOnly: true,
          require: {
            FunctionDeclaration: true,
            ArrowFunctionExpression: true,
            ClassDeclaration: true,
          },
        },
      ],
    },
  },
];
