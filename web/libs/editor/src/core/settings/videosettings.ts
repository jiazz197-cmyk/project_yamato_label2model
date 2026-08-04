import type { SettingsProperties } from "./types";

export default {
  videoDrawOutside: {
    description: "允许在视频边界外绘制",
    defaultValue: false,
    type: "boolean",
  },
  videoHopSize: {
    description: "视频步进大小",
    defaultValue: 10,
    type: "number",
  },
} as SettingsProperties;
