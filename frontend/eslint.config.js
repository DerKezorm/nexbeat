// ESLint nach der Vite-Vorlage fuer React und TypeScript, wie in Nexview.
//
// ⚠️ Die Schwelle steht auf null: `npm run lint` ruft `eslint . --max-warnings 0`.
// ESLint gibt bei reinen Warnungen Rueckgabecode 0 zurueck, ohne Schwelle waere
// der Schritt ein Pruefer, der nie anschlaegt.
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['**/dist/**'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', destructuredArrayIgnorePattern: '^_' },
      ],
      // Wie in Nexview: Entwurfs-State aus einer Abfrage vorbelegen ist das
      // Muster aller Einstellungsseiten.
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/refs': 'off',
    },
  },
)
