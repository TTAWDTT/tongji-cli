---
name: tongji-cli
description: 使用 tongji 命令查询同济大学课表、Canvas 作业和校园服务，按用户要求办理提交、预约等操作。适用于需要读取校方数据或复用本人校园登录的任务。
---

# tongji-cli

PyPI 包名是 `tongji-cli`，可执行命令是 `tongji`。先试 `tongji --help`。缺少命令时可用 `uv tool install tongji-cli` 或 `pipx install tongji-cli`。调用已安装的命令，当前目录可以是用户的作业目录。

## 从用户的问题选命令

| 用户想知道什么 | 从这里开始 |
| --- | --- |
| 今天有什么课、有什么作业到期 | `tongji today --json` |
| 接下来一周怎么安排 | `tongji week --json`，从今天起按上海日期合并七天的个人课表和作业 |
| 未来七天有哪些 Canvas 作业到期 | `tongji canvas assignments --next 7d --json` |
| 图书馆几点开门、还有多少空位 | 开放时间用 `tongji library hours --json`，余座用 `tongji library seats availability --json` |

查成绩时，教务成绩用 `tongji jw grades --json`，Canvas 课程总评用 `tongji canvas grades --json`。找录课回放用 `media`，查办事指南和办件用 `service`。其余参数按需查看对应子命令的 `--help`，如 `tongji media sessions --help`。完整命令和适用范围见[仓库 README](https://github.com/TTAWDTT/tongji-cli#readme)。

## 登录和结果判断

- 沿用运行环境的 `TONGJI_BROWSER`。Chrome 和 Chromium 各有独立的校园登录配置。需要核对身份时，只查相关站点，如 `tongji status --site canvas --json`。教务用 `jw`，图书馆空间预约用 `space`。公开查询可直接运行。
- 返回 `login_required` 时，打开对应站点，如 `tongji login --site canvas --json`，让用户在学校页面认证。等命令完成，查看 `after_restart` 是否为 `authenticated`。密码和 Cookie 留在浏览器里。
- 读取标准输出的 JSON，即使退出码非零也要看各来源的 `status` 和 `detail`。例如 `week.status` 为 `partial`、Canvas 有结果而教务要求登录时，照常报告已查到的作业，并说明课表暂缺。成功查询中的空列表表示该范围有零条记录；`unverified` 表示结果待核实。

## 从查询到办理

**交作业。** 先按用户给的课程和作业名定位，核对详情中的提交方式、作业 ID 和本地文件。下面的变量分别取本次查到的作业 ID、课程 ID 和用户指定的文件路径。

```sh
tongji canvas assignment show "$assignment_id" --course "$course_id" --json
tongji canvas assignment submit "$assignment_id" --course "$course_id" --file "$file" --preview --json
tongji canvas submission "$assignment_id" --course "$course_id" --json
```

第二条返回 `action: preview` 表示预览完成。用户已明确要求提交该份文件、预览与要求一致时，去掉 `--preview` 执行第二条，按返回的提交次数和时间报告结果。回执不明时先用第三条查本人提交记录，避免产生重复尝试。

**预约座位。** 用 `tongji library seats availability --json` 查看馆区余量，再用 `tongji library seats list --branch "$branch" --floor "$floor" --area "$area" --json` 查看指定区域的座号。“查空位”到这一步就已完成。用户要求预约时，用目标日期和本次列表里的馆区、楼层、区域、时段及完整座号（保留前导零）构造 `tongji library seats reserve`，先加 `--preview` 核对。正式办理后以匹配的预约记录为准；回执待核实时，先用 `tongji library reservations --kind seat --json` 查询。其他需要本人在校方窗口确认的业务，让用户完成对应步骤后再核对回执。
