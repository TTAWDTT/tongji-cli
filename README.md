# tongji-cli

同济校园服务的非官方命令行工具，可以查询教务课表、Canvas 作业、图书馆服务、校车和宿舍水电。个人查询使用自己的校园账号，登录在学校的认证页面完成。查询支持 `--json` 输出。

## 快速开始

用 [uv](https://docs.astral.sh/uv/getting-started/installation/) 或 pipx 从 [PyPI](https://pypi.org/project/tongji-cli/) 安装，任选一条命令即可。

```sh
uv tool install tongji-cli
# 或
pipx install tongji-cli
```

安装后可以在任意目录运行 `tongji --help` 查看命令。个人查询需要 Google Chrome，在 macOS 上安装 Chrome 后即可登录并查看本周安排。

```sh
tongji login
tongji week
```

如果终端找不到 `tongji`，按安装方式运行 `uv tool update-shell` 或 `pipx ensurepath`，然后重开终端。开发时仍可在仓库根目录运行 `./tongji`，它使用当前工作区的代码，与安装版共用登录配置。

## 供 Agent 使用

先在运行 agent 的环境里按「快速开始」安装 CLI，确认能运行 `tongji --help`。再把配套的 [SKILL.md](skill/SKILL.md) 下载到所用 agent 的技能目录。下面两种安装方式任选对应的一种，更新 skill 时可重跑同一条命令。

**Codex**

```sh
curl -fsSL --create-dirs -o "$HOME/.agents/skills/tongji-cli/SKILL.md" https://raw.githubusercontent.com/TTAWDTT/tongji-cli/main/skill/SKILL.md
```

**Claude Code**

```sh
curl -fsSL --create-dirs -o "$HOME/.claude/skills/tongji-cli/SKILL.md" https://raw.githubusercontent.com/TTAWDTT/tongji-cli/main/skill/SKILL.md
```

打开新的 agent 会话，在 Codex 里输入 `$tongji-cli 看看未来七天的课表和作业`，或在 Claude Code 里输入 `/tongji-cli 看看未来七天的课表和作业`。执行个人查询时，agent 需要能访问已登录的本机浏览器配置；如果使用 Chromium，请让它继承 `TONGJI_BROWSER=chromium`。其他支持 Agent Skills 的工具可将同一文件放入各自的技能目录，保留 `tongji-cli/SKILL.md` 这层结构。

## 登录与一周安排

`tongji login` 打开专用 Chrome，依次访问同济 Canvas 和教务工作台。请在学校页面完成认证，让命令自行关闭窗口。它会另起进程验证登录是否保留。专用配置位于 `~/.local/share/tongji-cli/chrome`。`tongji status` 默认检查教务与 Canvas。`--site service`、`--site library`、`--site jw`、`--site canvas`、`--site space`、`--site card`、`--site stadium` 和 `--site media` 可单查。`status --site all` 会检查全部八个站点，`login` 支持相同选项。学校要求重新认证时运行 `tongji login --site 站点名`。

如需将校园登录与日常 Chrome 窗口区分开，可在终端运行 `export TONGJI_BROWSER=chromium`。这个选项使用 Playwright 的 Chromium 及独立目录 `~/.local/share/tongji-cli/chromium`。尚未安装该浏览器时，运行 `uv run --with playwright==1.62.0 playwright install chromium`。登录和后续查询均在同一配置下运行。首次切换需在学校页面登录，新开终端时也要设置同一变量。

| 命令 | 查询范围 |
| --- | --- |
| `tongji today` | 上海日期当天的个人课表和当天截止的 Canvas 普通作业 |
| `tongji week` | 从今天起连续 7 天，按日期合并个人排课和作业截止项，含提交状态 |
| `tongji jw menu --search 导师` | 按本人 1 系统侧栏中的栏目、子菜单和入口名称搜索。省略条件列出全部入口，也可加 `--section 我的导师`。同名入口分别保留完整路径。需要经外部授权跳转的链接请从原菜单打开 |
| `tongji jw mentors profile freshman` | 查看本人的新生导师、简介和校方展示的联系方式。用 `college` 查学院导师，`mutual` 查互选导师；教务页面明确提示没有导师时，命令显示相应类别和空列表 |
| `tongji jw mentors meetings` | 查看新生导师见面会的学期、导师、所属学院、时间、地点、备注和发布时间 |
| `tongji jw graduation defenses` | 查看教务公布给本人的答辩年份、课题、校内指导老师、答辩时间和地点。学校尚未公布的字段留空 |
| `tongji jw graduation tasks --year 2026 --state 已通过` | 查询毕业设计任务书目录及状态。还可用 `--title`、`--advisor` 筛选，或用 `--page 2` 翻页。状态可选草稿、已通过、已撤销 |
| `tongji jw help-center list --search 成绩复核` | 按主题检索教务指南和常见问题，显示条目编号、类型、面向用户、状态和更新日期。同名条目分别列出 |
| `tongji jw help-center show 条目编号` | 读取该指南的正文、文内链接、附件名及附件编号 |
| `tongji jw help-center download 条目编号 --attachment 附件编号 --output ./form.doc` | 按 `show` 所列编号保存校方附件，输出路径须为新文件。请使用对应附件的扩展名 |
| `tongji jw forms list student-status --search 复学` | 查学籍管理的表格名称、说明、上传时间和编号。将目录换成 `graduation` 可查毕业设计表格和操作手册。省略 `--search` 可列出整份目录 |
| `tongji jw forms download graduation 文件编号 --output ./form.doc` | 下载该目录所列编号的文件。建议用列表中的原扩展名，CLI 核对校方下载文件名并保存到新路径。学籍表格用 `student-status` |
| `tongji jw major-timetable --term 2025-2026第2学期` | 查本人所在专业的学期课表，列出各教学班的周次、节次、教师和教室。同一时段在官网合并显示的教学班逐项列出。省略学期查当前学期，加 `--search 关键词` 可筛选排课文字 |
| `tongji jw progress list` | 查本人教学班、任课教师、教学进度状态和调课信息。加 `--search 关键词` 按课程或教师筛选，加 `--term 2025-2026第2学期` 查往期 |
| `tongji jw progress show 进度记录ID` | 用列表中的 ID 查看每次授课的时间、教师、地点和备注，以及答疑与审批进度。授课内容按教务公开范围显示。查看往期记录时须带上列表所用的 `--term` |
| `tongji jw schemes list` | 查“我的培养方案”里可选的方案名称、年级和编号。个人修读计划及完成学分分别见 `jw plan` 和 `jw credits` |
| `tongji jw schemes show 方案ID` | 读取章节正文、学分表和教学安排。加 `--chapter 基本学分要求` 可单查一章，章节名取自完整方案。教学安排保留分类行及各学期学时 |
| `tongji jw schemes image 方案ID --chapter 章节名 --index 1 --output ./diagram.png` | 按本章配图序号将校方原图保存为新文件，章节名和序号来自 `show` |
| `tongji jw competitions 数学建模 --level 省级 --valid 是` | 在教务“创新创业 → 竞赛目录查询”中按名称、竞赛等级及是否有效筛选，返回学校列出的获奖等级和备注。省略条件浏览目录，使用 `--page 2` 翻页；竞赛等级可选国际、国家、省级、校级 |
| `tongji jw applications list` | 查看教务工作台“我的申请”的申请编号、类型、申请时间、审批状态和当前处理人 |
| `tongji jw applications show 申请编号` | 用列表给出的完整编号查看详细修改、修改说明、审批材料文字及各步审批进度。详情附教务页面链接。校方列表若有重复申请编号，命令会提示无法唯一匹配 |
| `tongji jw notices list --search 期末` | 搜索本人教务工作台全部“通知公告”的标题，返回编号、发布日期和目录入口。省略 `--search` 列出全部。校方未提供发布日期时，JSON 中的 `date` 为 `null` |
| `tongji jw notices show 公告编号` | 按列表返回的编号打开原文，显示正文、文内链接、配图序号和页面列出的附件文字。纯图片公告可以接着用 `image` 保存 |
| `tongji jw notices image 公告编号 --index 1 --output ./poster.png` | 将公告的第 1 张正文配图按原始字节保存到新文件。图片序号取自 `show`，支持内嵌原图和校方页面允许浏览器读取的图片链接 |
| `tongji jw syllabus search 环境工程` | 在教务“教学大纲查询”目录按名称、课程编码或课程代码搜索，返回学分、学时、学院和大纲编号。省略关键词可浏览目录。加 `--page 2` 翻页，或用 `--term 2025-2026第2学期` 切换学期 |
| `tongji jw syllabus show ESE3383` | 按课程编码或代码读取校方大纲的基本信息和章节正文，包括该大纲列出的教学安排、考核和教材。若匹配多份，用 `--id 大纲编号` 选择。同样支持 `--term` |
| `tongji jw timetable --week this` | 本周一至周日。将 `this` 换为 `next` 查下周，使用 `--today` 查今天 |
| `tongji jw courses` | 研究生教务系统所选学期的课程清单，含教师、学分、考核方式、时间和地点。用 `tongji jw courses --term 2025-2026第2学期` 选定往期学期。学期名可取自 `calendar terms`，也可使用教务页面含“学年”的全名 |
| `tongji jw exams` | 本人教务考试表，保留当前页面可见的考试信息。尚未公布的字段为 `null` |
| `tongji jw grades` | 本人“选课网我的成绩”中的课程记录，按学校页面标示学期 |
| `tongji jw credits` | 当前账户的个人培养计划内各类别要求学分、个人计划学分和已完成学分 |
| `tongji jw plan` | 个人培养计划中的逐门课程，含课程类别、学分、是否必修、选课情况、成绩和完成情况 |
| `tongji jw plan export --output ./plan.zip` | 将教务原始培养计划压缩包保存到新路径。此次校方导出的包内为 PDF |
| `tongji jw enrollment status` | 个人选课页面明确提示未开放时返回 `closed`，显示“选择课程”入口时返回 `entry_visible` |
| `tongji jw enrollment requests` | 个人选课申请结果、状态与回复说明，保留校方分页中的全部记录 |
| `tongji jw retakes` | 返回重考申请窗口状态、学期和校方可见的课程。闭窗时保留教务提示 |
| `tongji jw retakes apply 新课程序号 --preview` | 开放时按唯一教学班核对申请对象。移除 `--preview` 会申请该门重考，再回读同一门课的申请状态。回执待核实时，先运行 `jw retakes` |
| `tongji jw enrollment apply 新课程序号 --term 学期 --preview` | 按个人课表显示的完整学期名核对课表和选课入口。教学班已在课表时返回 `already`，闭窗预览返回 `closed`。开放时去掉 `--preview`，本人在网页选课、保存并回终端按回车。目标教学班出现在同学期课表后返回 `verified` |
| `tongji jw withdrawals --apply 新课程序号 --term 学期 --preview` | 核对同学期的退课记录、课表和办理时间。已办结返回 `already`，闭窗预览返回 `closed`。2026 年秋季本科生按本科生院公告办理。其他学期如提示时间待核实，请先在教务页确认。去掉 `--preview` 后由本人办理，CLI 查到“已退课”且课表中已移除目标教学班后返回 `verified` |
| `tongji jw withdrawals` | 期中退课页面当前筛选条件下的课程、学期和状态。追加 `--verify 新课程序号` 会按同一学期和同一教学班核对个人课表 |

研究生课表使用校方学期起始日、排课星期、节次和周次，支持单双周及离散周。上课地点保留该课程在教务表中的原文；多时段课程的地点以原表和调课公告为准。不同身份可用的菜单由教务系统决定。

## 教学媒体平台

`tongji media courses` 列出智慧教学媒体资源管理平台「我的课程」的全部结果，自动翻页。每项包含课程 ID、名称、学期、主讲教师、上次学习和任务数。按课程名或教师名查找可运行 `tongji media courses --search 软件工程`。登录过期时运行 `tongji login --site media`。[同济智慧教学媒体资源管理平台](https://look.tongji.edu.cn/education/)

| 命令 | 在媒体平台上查什么 |
| --- | --- |
| `tongji media terms` | 列出「我的任务」中可选的学期代码 |
| `tongji media tasks --term 20261 --status 未完成` | 查询该学期未完成的必做任务，保留课程、起止时间和完成状态。默认查必做，省略学期查全部学期 |
| `tongji media tasks --term 20261 --kind optional --type 智播 --search 软件工程课程设计` | 按课程名或任务名查选做任务，自动翻页。任务类型取自平台选项；选做表没有完成状态栏 |
| `tongji media sessions --course 软件工程课程设计` | 按课程目录顺序列出各节课的周次、类型、标题、教师和校方状态。同名课程用 `media courses` 的 ID |
| `tongji media sessions --course 软件工程课程设计 --status 回放` | 仅列目录标为「回放」的课次。智播回放带学校播放页链接；视频能否播放取决于打开页面时的流状态 |
| `tongji media export 课次ID --course 软件工程课程设计 --output ./lecture.pptx` | 从上一条命令的结果中选一个有播放页链接的课次，把它的 ID 填在这里。默认只导出 PPT 课件 |
| `tongji media export 课次ID --course 软件工程课程设计 --include slides --include transcript --output ./lecture.docx` | 导出含课件和语音识别原文的 Word 文档。如需语音识别译文，再加 `--include translation` |

指定 `--include` 时只选显式列出的项目。只要选了语音原文或译文，请用 `.docx` 保存。目标目录必须存在，文件名须是新名字。校方生成文件期间，CLI 会等待并查询进度。若校方返回「暂无课件内容」，命令会报出原因，不生成文件。

## Canvas

先运行 `tongji canvas courses` 查找在读课程。查往期课用 `tongji canvas courses --state completed`，列表附学期；同名时用课程 ID。下列 `COURSE` 可使用列表返回的 ID、课程代码或能唯一匹配的课程名称。在读课的作业 ID 可用 `canvas assignments --course COURSE` 查，往期课的作业 ID 用 `canvas assignments --course COURSE --state completed` 查。

| 命令 | 结果 |
| --- | --- |
| `tongji canvas groups` | 查看本人当前小组、所属课程和学期。加 `--state completed` 查往期小组。只有校方目录提供入口的小组才返回链接和 ID |
| `tongji canvas navigation --course COURSE` | 按页面顺序列出本人可见的课程菜单和原链接，包括教师启用的录课回看等外部工具。查往期课加 `--state completed` |
| `tongji canvas navigation --group GROUP_ID` | 用 `canvas groups` 返回的 ID 查看该小组的菜单。往期小组有入口时，加 `--state completed` 查询 |
| `tongji canvas grades --state completed` | 查 Canvas 为本人已结课课程返回的总评。部分往期课的学生成绩页未展示接口返回的百分数。可用 `--course COURSE` 选一门。下列 `grading`、`assignment rubric`、`syllabus` 也可加 `--state completed` 查该门往期课 |
| `tongji canvas grades` | 查本人在读课程的 Canvas 总评。加 `--course COURSE` 只看一门。当前成绩按已评分项目计算，另列 Canvas 计入未评分作业后的成绩。空分值表示未提供；教师隐藏总评时显示“课程隐藏总评”。教务成绩用 `jw grades` 查询 |
| `tongji canvas grading --course COURSE` | 查看教师的作业分组、是否按组加权、舍去最高或最低几项及不参与本组舍分的作业 ID。各组列出作业满分、有发布时间的本人得分或等级，以及免交标记 |
| `tongji canvas assignment rubric ID --course COURSE` | 读取指定作业的评分量规，列出每项标准、评分等级、可见分值，以及教师是否用它评分。作业详情未提供量规时 JSON 中 `rubric` 为 `null` |
| `tongji canvas syllabus --course COURSE` | 读取课程大纲正文、链接和图片地址，附教师发布大纲的页面入口。响应中没有正文和资源时 `has_content` 为 `false` |
| `tongji canvas assignments --next 7d` | 未来 7 个上海日期内截止的普通作业和本人提交状态 |
| `tongji canvas assignments --due today` | 今天截止的普通作业 |
| `tongji canvas assignments --overdue` | 已过截止时间、Canvas 明确标为未提交的作业 |
| `tongji canvas assignments --course COURSE` | 该门在读课程全部可见作业，包括未设截止日期的作业 |
| `tongji canvas assignment show ID --course COURSE` | 作业要求、允许的提交方式、截止时间和原链接 |
| `tongji canvas inbox` | 默认列出未归档会话，含会话 ID、标题和最近一条消息。用 `--scope unread` 查未读，另可选 `starred`、`sent`、`archived`。加 `--course COURSE` 只看指定在读课程 |
| `tongji canvas recipients 姓名 --course COURSE` | 在指定课程内按姓名搜索本人可以发消息的用户。省略 `--course` 时按 Canvas 允许的范围搜索。结果含收件人 ID；同名用户分别列出 |
| `tongji canvas conversation send --course COURSE --to 收件人ID --subject 主题 --message 正文 --preview` | 从 `canvas recipients` 取得个人 ID。预览在 Canvas 编辑框核对收件人和课程。主题须为单行。去掉 `--preview` 会发送一次，并回读消息 ID、收件人、作者与正文。Canvas 复用已有私信时会保留原主题，回执显示实际会话标题。回执未核实时先用 `canvas inbox --scope sent` 查看，再决定是否重发 |
| `tongji canvas conversation show 会话ID` | 按 Canvas 返回的顺序读消息正文、发送人、附件和转发消息。命令保留会话原有的未读状态 |
| `tongji canvas conversation reply 会话ID --message 正文 --preview` | 预览显示全部直接收件人。对已读会话也会打开回复框核对；未读和归档会话仅读取原会话记录。去掉预览会在原会话回复所有直接收件人，打开未读会话可能将其标为已读。CLI 核对新增消息 ID、作者、正文及收件人。回执未核实时，先用 `canvas conversation show 会话ID` 核对再决定是否重发 |
| `tongji canvas conversation set 会话ID --state unread --preview` | 比较当前和目标状态。可选 `read`、`unread`、`archived`，或将 `--state unread` 换成 `--star on`、`--star off`。对已归档会话指定 `--state read` 或 `--state unread` 可解除归档。去掉预览会修改并重新读取状态。已达目标时返回 `unchanged`。结果未核实时可用 `canvas conversation show 会话ID` 查看 |
| `tongji canvas quiz list --course COURSE` | 列出学生可见的经典测验和 Canvas 标识为新测验的作业，含各自的 ID、类型、开放与截止时间。查看往期课程时，`quiz list`、`quiz show` 和 `quiz submission` 均可加 `--state completed` |
| `tongji canvas quiz show 测验ID --course COURSE` | 默认按经典测验 ID 取说明、时限和允许尝试次数。目录中 `engine` 为 `new` 的条目加 `--engine new`；设置受限时保留可见作业信息 |
| `tongji canvas quiz submission 测验ID --course COURSE` | 查看本人当前尝试及可见成绩。新测验同样使用 `--engine new`，返回已同步到 Canvas 作业系统的状态。查询不会开启一次作答。经典测验的作答记录查询失败时，如能读取关联作业的本人回执，返回 `partial` 并单列该回执 |
| `tongji canvas notifications` | 查看本人各渠道的通知项、类别和频率。可用 `--channel 渠道ID` 或 `--category announcement` 筛选；渠道状态可区分已启用和待确认 |
| `tongji canvas notification set --channel 渠道ID --category due_date --frequency daily --preview` | 预览指定渠道的截止时间提醒。去掉 `--preview` 会调整该类别下所有通知，保存后逐项回读。频率可选 `immediately`、`daily`、`weekly`、`never` |
| `tongji canvas announcements --since 7d` | 查全部在读课程近七天的公告，附正文和原链接，按发布时间降序。用 `--course COURSE` 只查一门课。加 `--state completed` 可查往期课程 |
| `tongji canvas announcements --group GROUP_ID --since 7d` | 从本人小组的公告栏读取已发布的公告。时间从上海日期窗口首日零点算到现在，定时公告按预定发布时间筛选。省略 `--since` 默认七天。往期小组有入口时可加 `--state completed` |
| `tongji canvas calendar --from 2026-11-01 --next 27d` | 默认只查个人日历。课程事件与作业截止项需要 `--course COURSE`；跨课程学习安排见 `canvas planner` |
| `tongji canvas discussions --course COURSE` | 列出该门课的讨论主题、未读数和回复数。查小组时，用 `canvas groups` 返回的 ID 指定 `--group GROUP_ID`。讨论列表和详情均可加 `--state completed` 查可进入的往期课程或小组 |
| `tongji canvas discussion create --group GROUP_ID --title "本周分工" --message "请各自认领一个用例。" --preview` | 核对小组的新讨论表单。去掉 `--preview` 会用页面的「保存」按钮创建主题，核对新 ID、标题和正文，并显示 Canvas 返回的发布状态。对已开放创建入口的在读课程，用 `--course COURSE`。如提示回执未核实，先查讨论列表 |
| `tongji canvas discussion show TOPIC_ID --course COURSE --replies` | 读取主题正文和本人可见的回复，保留父回复 ID。省略 `--replies` 只读主题。TOPIC_ID 来自讨论列表。查看往期课程的主题和回复时也加 `--state completed` |
| `tongji canvas discussion reply TOPIC_ID --group GROUP_ID --message "我来画用例图。" --preview` | 在当前小组核对普通主题和编辑框。在读课程用 `--course COURSE`。小组的主题 ID 取自该组的讨论列表。读正文和回复用 `discussion show TOPIC_ID --group GROUP_ID --replies`，用其中的发言 ID 加 `--parent ENTRY_ID` 回复指定发言。去掉 `--preview` 会发布回复并核对新增 ID、父帖和正文。匿名主题请在网页回复。若回执未核实，先查主题回复列表 |
| `tongji canvas planner --next 7d` | Canvas 学习计划，包含作业、测验、讨论等类型。加 `--from 2026-11-01` 指定起点，计划时间和截止时间各自保留 |
| `tongji canvas assignment submit ID --course COURSE --file ./work.pdf --preview` | 读取学校作业要求，核对提交类型、文件路径和扩展名。移除 `--preview` 会在当前账号尝试真实提交，可重复指定 `--file` |
| `tongji canvas assignment submit ID --course COURSE --text "作业正文" --preview` | 核对作业是否接受在线文本。交网址时改用 `--url https://example.org/project`。文件、文本、网址每次选一种。去掉 `--preview` 后会提交并核对本次尝试和内容 |
| `tongji canvas submission ID --course COURSE` | 本人的提交类型、时间、尝试次数、附件、可见成绩及反馈。文本提交保留正文及校方原始 HTML，网址提交返回所交链接。加 `--history` 按尝试编号查看历次交件时间、内容与附件 |
| `tongji canvas assignment download ID --course COURSE --attachment FILE_ID --output ./report.pdf` | 用 `canvas submission` 在本人提交或反馈的 `attachment_details` 中找到附件 ID。两处附件即使同名，也可按 ID 分别下载。指定 `--attempt N` 可取第 N 次本人交件的附件，反馈附件用默认查询。校验字节数后保存为新文件。往期课程加 `--state completed` |
| `tongji canvas pages --group GROUP_ID` | 列出所选小组的 Wiki 页面及每页的短标识（slug）。课程页面用 `--course COURSE` |
| `tongji canvas page show SLUG --group GROUP_ID` | 用同一小组列表里的 slug 读取正文、图片和链接。课程详情用 `--course COURSE`。两条命令均可加 `--state completed` 查可进入的往期小组或课程 |
| `tongji canvas files --course COURSE` | 查看课程文件名、文件 ID、大小和原链接。将 `--course COURSE` 换成 `--group GROUP_ID` 可查本人小组共享的文件，包含子文件夹中的文件 |
| `tongji canvas file download ID --course COURSE --output ./lecture.pdf` | 下载指定课程的文件。下载小组共享文件时，用 `--group GROUP_ID` 代替课程参数，文件 ID 取自该组的 `canvas files`。CLI 核对字节数并保存到新路径 |
| `tongji canvas materials --course COURSE` | 按教师的模块顺序列出学习页面、文件等，再补列课程文件目录中的其他附件 |

查以前交过的作业时，先运行 `tongji canvas courses --state completed` 取课程 ID，再运行 `tongji canvas assignments --course COURSE --state completed` 取作业 ID。用相同课程和作业 ID 运行 `canvas assignment show` 查要求，或 `canvas submission` 查本人提交与反馈，两条命令均加 `--state completed`。

查往期课件时，先用 `tongji canvas materials --course COURSE --state completed` 查模块和附件。从目录取得文件 ID 后，用 `tongji canvas file download ID --course COURSE --state completed --output ./handout.pdf` 保存到新路径。`canvas files`、`canvas pages` 和 `canvas page show` 也支持同一选项。往期课程可见内容取决于教师和学校的发布设置。

`--next` 和 `--since` 接受 `Nd` 格式的天数。提交状态为 `null` 表示 Canvas 的返回值不足以确认。实测部分课程的页面目录返回 HTTP 404。如果模块条目提供 slug，可从 `materials` 列出的页面 slug 读取已发布的模块页面。默认输出供终端阅读；`--json` 保留数字、布尔值和空值。

三种交件方式都在 Canvas 作业网页提交。预检读取作业允许的提交类型，核对本地输入。提交后，CLI 回读本人记录，确认尝试次数恰好增加一次、有提交时间、类型一致，并核对附件名称和大小、文本正文或所交网址。满足这些条件才返回 `action=submitted`。如果回执待确认，先用 `canvas submission` 查看本人最近一次提交，再决定是否重试。三种交件和回执匹配已在本地测试作业验证，学校生产环境的实际交件仍待验收。五门在读课程的可见作业中没有接受文本或网址的样本。

测验目录分别读取经典测验和课程作业，两者的读取结果列在 JSON 的 `sources` 中。任一来源失败时保留已取得的条目，返回 `partial` 并以退出码 1 结束。两边都失败且未取得条目时返回 `unverified`。未完整读取的空列表无法证明课程没有测验。从作业列表识别到的经典测验，详情和本人尝试仍需访问经典测验接口。

## 校园服务

| 命令 | 结果或操作 |
| --- | --- |
| `tongji calendar week` | 当前学期、周次、周一和周日；可追加 ISO 日期 |
| `tongji calendar terms --year 2026` | 按学年起始年份查看校方公布的学期起止日期、教学周和考试周范围。省略年份列出完整目录 |
| `tongji calendar range 2026-11-23 2026-11-29` | 日期两端都包含，每天返回校方标记及来源。部分日期缺失或标记无法识别时保留其余日期，返回 `partial` 及退出码 1。整个区间查不到时返回 `unverified` |
| `tongji calendar day 2026-11-27` | 指定日期的校历标记与周次。“工作日”本身不能说明节假日调上哪天的课 |
| `tongji notices list --source graduate --page 2` | 按校园官网目录页列出标题、日期及原文。支持 graduate、undergraduate、library、sports、jiading、all。jiading 是嘉定校区管委办的日常通知，含交通和临时改站公告。体育部提供一页通知通告 |
| `tongji notices search 选课 --pages 3` | 在每个所选来源的指定页数内查找标题，可用 `--page` 指定起始页 |
| `tongji notices show URL` | 从通知原文读取日期、正文、附件与图片链接，原文仅提供 PDF 时返回 PDF 链接 |
| `tongji library reservations --kind seat --limit 12` | 按馆方顺序读本人座位预约记录，含位置、馆方显示的时间和状态。可换为 `room`（空间）或 `research`（研修专座），默认最多 10 条 |
| `tongji library loans` | 使用专用会话查本人当前借阅的图书、现刊与应还日期 |
| `tongji library renew 条码号 --due YYYY-MM-DD --preview` | 用当前在借图书的条码号和原应还日期核对单册。去掉 `--preview` 会为这一册提交续借。只有重新查询到同一借阅的新应还日期晚于原日期时，才返回 `renewed` |
| `tongji library loans --history` | 按图书、现刊读取馆方借阅历史，包含题名、条码号、借阅日期、应还日期、实还日期。同一本书多次借阅会逐次列出 |
| `tongji library hours 四平` | 馆方公布的常规开放时间；省略馆区可查全部，节假日以临时通知为准 |
| `tongji library search 软件工程` | 查询官方馆藏的书名、页面列出的书目信息与详情链接。纸本书目返回 ID，使用 `--page 2` 翻页 |
| `tongji library holdings 125089` | 用 `library search` 返回的书目 ID 查询。逐册显示馆藏地、索书号、条码号、书刊状态及借阅属性，同时返回馆方按馆藏地列出的可借复本和当前请求数 |
| `tongji library seats availability` | 进入校方座位预约页，按馆舍返回页面所选日期的空余数、总数和读取时间。馆方通知要求在校内网络环境访问 |
| `tongji library seats availability --branch 嘉定校区图书馆 --floor 二楼` | 列出二楼各区域的空余数和总数。省略 `--floor` 可列出该馆各楼层。加 `--date YYYY-MM-DD` 可查询馆方已开放的日期 |
| `tongji library seats list --branch 嘉定校区图书馆 --floor 二楼 --area 二楼北` | 按馆方列表返回可选座位号、日期和时段，保留座位号前导零。可加 `--date YYYY-MM-DD` 和 `--time 08:00-22:00` |
| `tongji library seats reserve --date YYYY-MM-DD --branch 嘉定校区图书馆 --floor 二楼 --area 二楼北 --time 08:00-22:00 --seat 397 --preview` | 在馆方页面选中座位并核对座号，显示是否已开放提交和馆方按钮上的倒计时。把日期、时段和座号替换为所需值。倒计时期间会提示尚未开放。预约开放后，去掉 `--preview` 会点击“立即预约”，再到本人记录核对地点、座号、日期、时段和状态。若未确认，请先用 `library reservations` 核对 |
| `tongji library rooms dates` | 列出馆方当前可选的日期，标出页面默认选中的一天 |
| `tongji library rooms list --branch 嘉定校区图书馆 --floor 二楼` | 列出所选馆舍及楼层的预约空间，含名称、类型和空间编号。省略筛选可看全部。加 `--date YYYY-MM-DD` 或 `--type 多人研讨室` 按日期或馆方类型筛选。从结果取空间编号，再用 `rooms slots` 查具体时段 |
| `tongji library rooms receipts` | 列出本人最新 10 条研习空间回执，含编号、申请主题、提交时间和馆方状态。用 `--limit 3` 控制列表长度，或用 `--id 回执编号` 从全部本人记录中精确查一件。列表保留已取消及已使用记录 |
| `tongji library rooms slots 44` | 按房间编号查看馆方时段页列出的日期、开放时间、已占时段、剩余空档、达到最短时长的空档，以及单次预约时长和人数上下限。可加 `--date YYYY-MM-DD` 只取一天。空档可能短于最短预约时长；实际可办理的日期以该房间时段页为准 |
| `tongji library rooms reserve 44 --date 2026-11-28 --time 12:00-13:00 --preview` | 将示例编号、日期和时段换成本次查询结果。预览在馆方页面选好房间及时间并核对申请表，显示表单项目和可选主题。可加 `--topic 自主学习 --purpose "复习课程材料"` 预填主题和用途。正式办理时在交互终端去掉 `--preview`，由本人填写用途、成员等馆方要求的信息并提交。CLI 在办理前读取本人已有的空间预约编号。按回车后，它在最新 10 条记录内查找唯一的新编号，并核对房间、完整日期、起止时间及办理状态。回执为“待审核”时，需等馆方审核。结果待核实时，先查 `library reservations --kind room` |
| `tongji library study availability` | 查研修座位的馆舍余座。加 `--branch 馆名` 查各楼层，再加 `--floor 楼层` 查区域。三条 `study` 命令都可以加 `--type exam` 切换到考研座位 |
| `tongji library study list --branch 嘉定校区图书馆 --floor 九楼 --area 九楼阅览区 --period next` | 查选定区域和周期的空闲座号、完整起止日期及本人预约权限。省略周期时查本期；馆方尚未列出下期时，命令会说明原因 |
| `tongji library study reserve --branch 嘉定校区图书馆 --floor 九楼 --area 九楼阅览区 --period current --seat 052 --preview` | 将馆区、区域和座号换成本次列表中的值。预览会选中这个座号并显示馆方按钮及当前能否预约。去掉 `--preview` 后，权限和按钮均允许时，由本人在馆方窗口确认办理，按回车核对记录。只有在本人最新 10 条研修专座记录中找到先前没有的有效预约，且地点、座号与起止日期完整匹配，才报告成功。回执待核实时先用 `library reservations --kind research` 查看 |
| `tongji library seats open` | 在默认浏览器打开官方空间预约页面，选座与预约在馆方页面完成 |
| `tongji bus next --from 嘉定 --to 四平` | 两校区间下一趟可核实的学生定班车，含计划时间、上车点、依据。反向查询交换校区 |
| `tongji service applications` | 一网通办个人中心的“我发起的”，显示校方列出的状态和最近处理时间 |
| `tongji service applications --with-flow` | 逐件打开“流程”。非空步骤的页面文本与校方响应能逐项核对时返回记录。校方未提供可核实的结果时保留办件摘要，标记该件为 `unverified`，整条命令返回 `partial` |
| `tongji service tasks` | 本人待办与已办，支持 `--state pending`、`--state processed` |
| `tongji service apply 校园绿地使用申请表 --preview` | 以事项全名核对同心搭服务和填写页。实际办理时在交互终端去掉 `--preview`，由本人核对材料并提交。回到终端按回车后，CLI 在“我的申请”中核对该事项的唯一新增办件并返回编号。正式环境已预览该表单，新增办件回读仅在本地测试验证。老版门户事项另走各自页面 |
| `tongji service apply 本科生学生证补办 --source portal --preview` | 在旧门户按完整事项名匹配卡片。这个事项列有办事指南，命令返回校方办理说明。就业网的已知登录页会返回登录状态。学生班车事项转到校方时刻表，无法核实的目标页面返回 unverified |
| `tongji service apply 学生电子证明文件 --source portal --preview` | 列出电子证明中心的模板和已完成件数。加 `--template 模板全名` 只核对该名称是否唯一。要办理，在交互终端指定模板并去掉 `--preview`，本人在官网选模板办理后回终端按回车。只有该模板新增唯一已完成订单才返回 `receipt`，其余情况请用 `service certificates` 复核 |
| `tongji service certificates` | 读取本人“已完成文件”的校方列、模板名及订单号。用 `--template 模板全名` 按模板名称精确筛选 |
| `tongji service certificate download 订单号 --preview` | 用 `service certificates` 返回的完整订单号打开已完成文件的详情，核对文件名称，并确认“再次下载”按钮可用。要保存 PDF，把 `--preview` 换成 `--output ./证明.pdf`。目标目录须已存在，文件名须未占用。CLI 检查文件可被 PDF 阅读器解析且含页面后保存 |
| `tongji service forms 结业` | 在研究生院常用下载的全部目录页按标题检索表格和指南。省略关键词列出全部 |
| `tongji service form URL` | 查材料说明和附件名称。加 `--attachment "完整附件名" --output ./申请表.doc` 打开官方附件页。若出现验证码，在窗口完成后，CLI 将收到的附件保存到新路径 |
| `tongji service find 在读证明` | 用当前登录会话检索一网通办事项，并合并公开服务指南，返回匹配事项、官方入口和来源列出的办理说明 |
| `tongji bus shuttle --date 2026-11-27 --from 嘉定` | 查嘉定校区与地铁 11 号线上海汽车城站之间的短驳车，返回当日各班的发车时刻、上车点和公告。省略方向查双向，省略日期查上海当天 |
| `tongji bus shuttle --line 14 --from 封浜` | 查 14 号线封浜站至嘉定校区的嘉定 DZ1 线，省略方向可查双向。支持 `--date YYYY-MM-DD`。封浜实际发车以公交到站为准。默认线路仍为 11 号线 |
| `tongji sports hours --campus 嘉定 --venue 网球` | 筛选体育部 2026–2027 学年第一学期开放方案，可省略两个筛选项。临时调整及场次预约以体育部最新通知和预约页为准 |
| `tongji sports venues --campus 四平 --venue 网球` | 列出预约平台的场馆名、地址和开放时间，可省略筛选条件 |
| `tongji sports slots --venue 四平校区爱校路网球场 --date YYYY-MM-DD` | 登录过期时运行 `tongji login --site stadium`。按官网开放日期查询每片场地的时段和可选状态。场馆有多个项目时须指定 `--sport 项目名`。无法识别的格子显示“未核实” |
| `tongji sports orders` | 列出本人场馆订单，含订单号、场馆、日期、场次、金额和平台状态 |
| `tongji sports reserve --venue 沪西校区羽毛球馆 --date YYYY-MM-DD --field 场地1 --time 12:00-13:00 --preview` | 用 `sports slots` 返回的场地名、日期和时段核对单个场次及合计金额。在交互终端移除 `--preview`，由本人在可见窗口完成下单，然后按回车。CLI 在个人订单中核对相同场馆、日期、场地和时段的新增订单，保留校方状态 |
| `tongji clinic hours --department 中医科` | 查询门诊部与医院分别公布的科室安排。加 `--facility 同济大学门诊部` 筛选机构。挂号流程见 `clinic guide` |
| `tongji clinic guide` | 从校医院读取门诊流程与指南中列出的科室开放时间，附原文链接 |
| `tongji card transactions --from 2026-11-01 --to 2026-11-26` | 按所选起止日期读取本人一卡通流水的全部页，保留入账时间、交易时间、地点、金额和卡余额。默认查至上海日期今天，含截止日在内共 7 天 |
| `tongji card balance` | 通过一卡通平台的统一认证入口，在本人个人中心读取账户余额，保留金额的小数位 |
| `tongji dorm guide` | 读取后勤处购电和查询水电余额的指南，附配图与服务中心的“水电查询”校内入口 |
| `tongji dorm locations --campus 嘉定校区ISIMS --building 友园2号楼` | 在能访问后勤处水电系统的网络中，查看该楼的“楼层”选项。省略楼栋可列该校区的楼栋，两个参数都省略时列校区及计量系统。选项沿用校方原名，可能包含“公用”等区域 |
| `tongji dorm electricity --meter 校区 楼栋 楼层 房号` | 在能访问后勤处水电网页的网络中查本人指定电表的剩余度数和查询时间。前三项用 `dorm locations` 的原名，房号可用页面上的完整名称，也可用与楼栋名拼接后唯一匹配的短房号 |
| `tongji dorm usage --meter 校区 楼栋 楼层 房号` | 查同一电表最近七天的每日用量和单价（元/度）。可加 `--from YYYY-MM-DD --to YYYY-MM-DD`，CLI 会读取全部结果页，按日期升序输出。只列出校方有记录的日期 |
| `tongji dorm water --meter 校区 楼栋 楼层 房号` | 查询本人宿舍水表余量（吨）和查询时间。四项选择方法与电表相同 |
| `tongji dorm water-usage --meter 校区 楼栋 楼层 房号` | 查最近七天有记录的每日用水量（吨）和校方单价（元/吨）。可用 `--from YYYY-MM-DD --to YYYY-MM-DD` 指定日期，结果按日期升序排列 |
| `tongji dorm electricity` | 读取授权学生对应的房间、剩余电量、累计购电量和累计用电量。累计数属于房间 |
| `tongji dorm usage --from 2026-11-20 --to 2026-11-26` | 读取该房间指定日期内的逐日用电量。按上海日期筛选、升序输出，保留校方原始时间。未指定截止日时用今天，未指定起始日时从截止日前 6 天开始 |
| `tongji card guide` | 从信息办读取一卡通使用指南，含充值、挂失、解挂和补卡说明 |
| `tongji rooms search 安楼` | 用关键词获取公开教室信息系统所列的教室名称 |
| `tongji rooms status 嘉定校区-安楼-105` | 从匹配列表复制完整教室名。匿名查询校方显示的状态、教室情况、自习可用时长及页面时间 |
| `tongji rooms buildings --campus 嘉定` | 查询教务教学楼名称与编号，可省略校区查全部 |
| `tongji rooms list --building BUILDING_CODE` | 列出该教学楼的教室 ID，供 `rooms schedule --room` 使用 |
| `tongji rooms schedule --room ROOM_ID` | 使用教室编号查询校方课表，可用 `--term` 指定学期编号 |

班车默认按上海当前时间查询，也可传 `--at 2026-11-27T12:00`。定班车时刻依赖校方发布的图片，程序校验图片版本，并读取公告匹配当日临时安排。此查询返回计划时刻。`rooms buildings`、`rooms list` 和 `rooms schedule` 需校方为应用开通相应客户端模式权限，并通过环境变量 `TONGJI_OPEN_TOKEN` 提供有效 Bearer 令牌。教室排课表只说明排课占用情况。[教室课表接口](https://api.tongji.edu.cn/docs/interface/teaching_management_data/educational_administration_data/teach_timetable/v1_rt_onetongji_classroom_get_timetable_by_classroom)

指定 `--meter` 时，CLI 通过后勤处服务中心的“水电查询”入口读表，无需开放平台令牌。只有 `dorm electricity` 和 `dorm usage` 可省略 `--meter`，此时使用学校开放平台的能源中心接口。用 `TONGJI_USER_TOKEN` 提供获准访问相应接口的本人授权码模式访问令牌。CLI 省略可选的学号参数。当前校方带令牌的房间匹配与取数仍待验证。也可用 `dorm guide` 查看同济大学移动门户小程序“购电应用”的说明。[后勤处用电指南](https://hqc.tongji.edu.cn/29/83/c30795a338307/page.htm) · [房间电量接口](https://api.tongji.edu.cn/docs/interface/school_management_data/logistics_and_security_management_data/other_nyzx/v1_rt_nyzx_electricity_user) · [逐日用电接口](https://api.tongji.edu.cn/docs/interface/school_management_data/logistics_and_security_management_data/other_nyzx/v1_rt_nyzx_electricity_user_record)

## 输出和验证

每个来源返回 `status` 和可用的 `items`。有效查询可以有 0 项。站点要求登录时返回 `login_required`，数据或授权无法核实时返回 `unverified`。聚合查询会保留成功来源。`service find` 分别给出公开指南和一网通办的读取状态，门户需要重新登录时仍会返回可读的公开指南。`week` 在缺少来源时返回 `partial`，受影响字段省略，进程以非零状态退出。

校园登录有效期由学校决定。教学楼、教室目录和课表的开放平台接口已用本地样例测试，生产环境仍需相应授权。

本地回归使用临时服务器与 Chrome，可在本目录执行：

```sh
uv run python -m unittest discover -s tests -v
```

## 学习通网页版（本地扩展）

使用同一专用浏览器配置保存学习通会话；在超星官方网页登录后可读取课程、普通作业和提交状态。

```sh
tongji login --site chaoxing
tongji status --site chaoxing --json
tongji chaoxing courses --json
tongji chaoxing assignments --json
tongji chaoxing assignments --course "课程ID:班级ID" --next 7 --json
tongji week --json
```

`week` 同时查询教务、Canvas、学习通。学习通作业放在每天的 `chaoxing_assignments` 中；截止时间缺失或缺少年份的作业放在 `week.undated_assignments`，保留 `due_as_listed` 原文。`today` 只列出能确认当天截止的作业。部分来源失败时保留其他结果并返回 `partial`，非零退出码不代表没有可用数据。

课程范围是当前机构“我学的课”目录，不含归档目录和其他机构；作业不包括考试、章节测验。`--next` 以上海日期筛选，截止时间未知的条目仍保留。课程同名多班时使用 `courses` 返回的复合 ID。页面无法识别时返回未核实，不将其当作零项。登录过期或出现验证时，在官方页面重新认证。

此扩展只读取学习通信息，不提供交作业、考试、签到或代学操作。首次登录使用通用官方入口，可在官方登录页选择单位账号或其他登录方式；尚未单独验证各校定制门户。
