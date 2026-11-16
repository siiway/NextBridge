import DefaultTheme from "vitepress/theme";
import type { Theme } from "vitepress";
import ThemeLayout from "./ThemeLayout.vue";


export default {
  extends: DefaultTheme,
  Layout: ThemeLayout,
} satisfies Theme;