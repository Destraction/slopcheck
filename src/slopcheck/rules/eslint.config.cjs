// Конфиг ESLint для slopcheck: React/TS-смеллы, мёртвый код, JSDoc экспортов.
//
// Лежит в пакете slopcheck, а не в проверяемом репозитории, поэтому:
//   - плагины грузятся из глобального node_modules (SLOPCHECK_NODE_MODULES,
//     `npm root -g`): обычный require искал бы их рядом с этим файлом;
//   - basePath = SLOPCHECK_ROOT: без него ESLint 9 считает файлы вне каталога
//     конфига «вне base path» и молча их пропускает.
// Все правила — "warn": категорию и severity находки задаёт адаптер.
const path = require("node:path");
const { createRequire } = require("node:module");

const modulesDir = process.env.SLOPCHECK_NODE_MODULES;
const load = modulesDir
  ? createRequire(path.join(modulesDir, "_slopcheck.js"))
  : require;

const tseslint = load("typescript-eslint");
const react = load("eslint-plugin-react");
const reactHooks = load("eslint-plugin-react-hooks");
const jsdoc = load("eslint-plugin-jsdoc");

module.exports = [
  {
    basePath: process.env.SLOPCHECK_ROOT || process.cwd(),
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
      "react/no-unstable-nested-components": "warn",
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
