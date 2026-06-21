import js from '@eslint/js';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import tsParser from '@typescript-eslint/parser';
import astroPlugin from 'eslint-plugin-astro';
import globals from 'globals';

const sourceFiles = ['**/*.{js,cjs,mjs,ts,tsx,astro}'];

export default [
  {
    ignores: [
      'dist/',
      '.astro/',
      'node_modules/',
      'public/',
      'tests/visual/__snapshots__/',
      'scripts/build-og-images.mjs',
      'src/pages/protocols/**',
    ],
  },
  {
    files: sourceFiles,
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.node,
        ...globals.es2022,
      },
    },
    rules: {
      ...js.configs.recommended.rules,
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },
  ...tsPlugin.configs['flat/recommended'].map((config) => ({
    ...config,
    files: ['**/*.{ts,tsx}'],
  })),
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
    },
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/triple-slash-reference': 'off',
    },
  },
  ...astroPlugin.configs['flat/recommended'],
  {
    files: ['**/*.astro', '**/*.astro/*.js', '**/*.astro/*.ts'],
    rules: {
      'no-var': 'off',
      'no-undef': 'off',
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': 'off',
    },
  },
];
