/** @type {import('jest').Config} */
module.exports = {
  preset: "ts-jest",
  testEnvironment: "node",
  roots: ["<rootDir>/src", "<rootDir>/test"],
  testMatch: ["**/*.test.ts"],
  clearMocks: true,
  collectCoverageFrom: ["src/**/*.ts", "!src/index.ts"],
  coverageThreshold: {
    global: { lines: 60, statements: 60 },
  },
  transform: {
    "^.+\\.ts$": ["ts-jest", { tsconfig: "tsconfig.json", diagnostics: { warnOnly: false } }],
  },
};
