# 参与方式

这个项目跑的是**真实价格**，任何一条数据你都能自己去麦当劳 App 里核对。欢迎校正。

## 想加一座城市

不用改代码清单——城市清单在 `src/cities_cn.py`：

- 地级市 → 加进对应省份的 `REGIONS`
- 百强县之类的县级市 → 加进 `EXTRA_CITIES`

加完之后重跑探测即可（需要 MCP Token）：

```bash
python src/probe_cities.py                 # 重新探测全国门店
python src/survey_national.py --city 某某  # 只补这一城
python src/render_report.py                # 重新渲染 dist/report.html
```

## 觉得某个价格不准

`data/surface_national.json` 里每座城市都留了门店名、门店编号、核价日期。
先在 App 里核对同一家店、同一天的同一件商品：

- 确实不一致 → 开 issue，带上「城市 + 门店编号 + 商品名 + 你看到的价格 + 截图」
- 是不同门店的定价差异 → 不必报，这是正常现象（页面里只展示同一时刻同店的对比）

## 代码约定

- **零第三方依赖**：只用 Python 3.10+ 标准库，`requirements.txt` 只是显式声明
- **只读**：不调用任何下单、领券、支付类工具（详见 `skill/SKILL.md` 的白名单）
- **不入库**：Token 只走环境变量，`.env` 已被 `.gitignore` 排除
- **排版不能错乱**：改完 HTML 请跑一遍体检，四视口都不许有横向滚动
  ```bash
  python src/check_layout.py
  ```
- **交互不能是坏的**：改了答案卡/预算搭配器，请跑无头浏览器实测
  ```bash
  python src/check_combo.py
  ```
- **改动流传跑测试**
  ```bash
  python -m unittest discover tests
  ```

## 提交 PR 前

1. `python -m unittest discover tests` 通过
2. `python src/check_layout.py` 四个视口全绿
3. 改了答案卡或预算搭配器的话，`python src/check_combo.py` 也要过
4. 如果改了数据口径，请在 issue 里说明影响范围（哪些城市/哪些结论会变）
