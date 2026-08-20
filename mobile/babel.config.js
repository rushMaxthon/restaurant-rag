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
          '@components': './src/components',
          '@services': './src/services',
          '@hooks': './src/hooks',
          '@store': './src/store',
          '@types': './src/types',
          '@utils': './src/utils',
        },
        extensions: ['.ios.ts', '.android.ts', '.ts', '.ios.tsx', '.android.tsx', '.tsx', '.js', '.json'],
      },
    ],
    'react-native-reanimated/plugin',
  ],
};
