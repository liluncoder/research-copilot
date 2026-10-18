import type { Metadata } from "next";
import "./globals.css";

/*
 * ★这里原本有两处硬伤，是"整站显脏"和"构建卡住"的共同来源：
 *
 * 1) <html className="dark"> —— 整站被强制暗色。而各页面写的是浅色设计（白卡片 + 深字），
 *    在 dark 变量下变成"深底 + 深字/白卡片混搭"，必然浑浊。现在默认浅色。
 * 2) next/font/google 的 Inter —— 构建期要去 fonts.googleapis.com 拉字体文件。
 *    离线 / Docker 无外网 / 国内网络下会长时间挂住或直接失败。
 *    字体改由 tailwind fontFamily 的系统栈提供（中文苹方/雅黑，西文 Segoe/Inter），零网络请求。
 */
export const metadata: Metadata = {
  title: "科研助手 Agent · Research Copilot",
  description: "全流程科研助手 Agent：文献解析、抗幻觉问答、联动翻译、引用图谱、写作辅助",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="font-sans">{children}</body>
    </html>
  );
}
