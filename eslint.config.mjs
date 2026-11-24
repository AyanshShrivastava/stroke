import firebaseRulesPlugin from '@firebase/eslint-plugin-security-rules';

export default [
  {
    ignores: ['dist/**/*', 'node_modules/**/*', 'src/**/*', '*.ts', '*.tsx'],
  },
  firebaseRulesPlugin.configs['flat/recommended'],
];
