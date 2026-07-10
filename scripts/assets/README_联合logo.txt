联合 logo 合成资源
==================

把两张图放到本目录后，在项目根执行：

  python scripts/combine_joint_logo.py

或指定路径：

  python scripts/combine_joint_logo.py --logo1 图1路径.png --logo2 图2路径.png -o output/joint_logo.png

约定：
- logo1.png：前面可替换 logo（图1）
- logo2.png：后面固定 logo（图2，如 LEGION ZONE）

合成规则：图1 — 20px — 22×22 白色 X 按钮 — 20px — 图2，整体高度 50px，输出到 output/joint_logo.png。
