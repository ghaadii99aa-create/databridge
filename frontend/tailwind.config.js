/** DataBridge design tokens. See docs/DESIGN_SYSTEM.md. */
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F7F6F2",      // app background
        surface: "#FFFFFF",    // tables, panels
        ink: { DEFAULT: "#242824", soft: "#4A4F49", muted: "#5E625B", faint: "#686C65" },
        forest: { DEFAULT: "#526B58", deep: "#3E5444", light: "#7F9784" },
        sage: { DEFAULT: "#DCE5DC", soft: "#EBF0EA" },
        stone: { DEFAULT: "#E8E6DF", line: "#DEDBD2", dark: "#CFCBC0" },
        clay: { DEFAULT: "#B87559", deep: "#8A5039", soft: "#F3E6DF" },
        amber: { DEFAULT: "#A9851C", soft: "#F4ECD6" },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
        xs: ["0.75rem", { lineHeight: "1.1rem" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.875rem", { lineHeight: "1.4rem" }],
        md: ["1rem", { lineHeight: "1.5rem" }],
        lg: ["1.25rem", { lineHeight: "1.75rem" }],
        xl: ["1.625rem", { lineHeight: "2rem", letterSpacing: "-0.01em" }],
        "2xl": ["2.25rem", { lineHeight: "2.5rem", letterSpacing: "-0.02em" }],
      },
      borderRadius: { DEFAULT: "4px", sm: "3px", md: "6px" },
      boxShadow: {
        panel: "0 1px 0 rgba(36,40,36,0.04)",
        pop: "0 8px 24px -8px rgba(36,40,36,0.18), 0 0 0 1px rgba(36,40,36,0.06)",
      },
    },
  },
  plugins: [],
};
