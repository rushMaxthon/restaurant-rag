module.exports = {
  preset: '@react-native/jest-preset',
  setupFiles: ['<rootDir>/jest.setup.js'],
  // React Navigation and the react-native-* libraries ship untranspiled ES
  // modules; the preset only compiles a package named exactly react-native.
  transformIgnorePatterns: [
    'node_modules/(?!((jest-)?react-native(-[^/]+)?|@react-native(-community)?|@react-navigation|standard-navigation)/)',
  ],
};
