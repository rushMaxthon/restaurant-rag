// Path aliases must match tsconfig.json's "paths" exactly, or an import that
// type-checks will fail to resolve at bundle time (the kitchen app learned
// this one). The worklets plugin must stay LAST: it rewrites functions marked
// 'worklet' so Reanimated can run them on the UI thread, and a plugin after it
// would transform code it has already moved.
module.exports = {
  presets: ['module:@react-native/babel-preset'],
  plugins: [
    [
      'module-resolver',
      {
        root: ['./src'],
        alias: {
          '@': './src',
          '@screens': './src/screens',
          '@navigation': './src/navigation',
          '@components': './src/components',
          '@services': './src/services',
          '@hooks': './src/hooks',
          '@store': './src/store',
          '@theme': './src/theme',
          '@utils': './src/utils',
        },
        extensions: ['.ios.ts', '.android.ts', '.ts', '.ios.tsx', '.android.tsx', '.tsx', '.js', '.json'],
      },
    ],
    'react-native-worklets/plugin',
  ],
};
