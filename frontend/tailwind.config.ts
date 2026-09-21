import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef6ff",
          100: "#d9eaff",
          500: "#1d5bd6",
          600: "#164ab2",
          700: "#123b8d",
          900: "#0b2456",
        },
        aqi: {
          good: "#009966",
          satisfactory: "#8bc34a",
          moderate: "#ffde33",
          poor: "#ff9933",
          veryPoor: "#cc0033",
          severe: "#7e0023",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
