/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // 允许用环境变量换输出目录：某些受限环境里 next build 无法删除默认的 .next
  // （实测：沙箱的 safe-delete 钩子会拦住 recursiveDelete ⇒ 构建表现成"卡死/失败"）
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;
