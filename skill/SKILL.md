---
name: tongji-cli
description: 使用 tongji 查询同济大学教务课表、Canvas 与学习通作业、录课、图书馆和校园服务；适用于需要复用本人校园登录、下载校方材料、提交作业、预约或核对办理回执的任务。
---

# tongji-cli

PyPI 包名为 `tongji-cli`，终端命令为 `tongji`。先用 `tongji --help` 核对入口；缺少命令时可用 `uv tool install tongji-cli` 或 `pipx install tongji-cli`。在用户的工作目录里调用安装版即可。下文的 `$course_id` 等变量表示从上一步结果或用户请求取得的值，日期用 YYYY-MM-DD。按任务选择一条路径，不必依次执行每个示例。

## CLI 提供的业务原子操作

用户已经指定对象、动作和范围时，直接调用对应命令。例如“查这门课的总评”只需一次成绩查询。“把这个 PDF 交到这份作业”也是一个业务动作：提交命令负责上传、提交和核对回执。Agent 负责在调用前选对课程、作业和文件。

下表按输入和结果选命令。示例中的 ID 来自对应站点。查询返回的 ID 可以作为下一次操作的输入；用户需求已经满足时即可停止。

| 对象与动作 | 调用示例 | 结果能说明什么 |
| --- | --- | --- |
| 个人课表，指定自然周 | `tongji jw timetable --week this --json` 或 `tongji jw timetable --week next --json` | 本周或下周一至周日的排课、节次和原表地点 |
| 校历，指定日期 | `tongji calendar week "$day" --json` | 当天属于哪个学期、第几教学周 |
| 教务成绩 | `tongji jw grades --json` | 教务系统公布的成绩。Canvas 的课程总评从该课程的 grades 读取 |
| Canvas 普通作业，指定截止窗口 | `tongji canvas assignments --next 7d --json` | 未来七个上海日期内截止的普通作业及本人提交状态 |
| Canvas 学习计划，指定起点和天数 | `tongji canvas planner --from "$start" --next 7d --json` | 窗口内的计划条目，含类型、计划时间和可取得的截止时间 |
| 一份作业，读取或提交 | `canvas assignment show` 读要求，`canvas assignment submit` 提交，`canvas submission` 读本人记录 | 三个动作各有结果。submit 成功时返回该次回执，submission 还可用来查历史或核对不确定的结果 |
| 教学媒体课程与课次 | `media courses` 按课程名检索，`media sessions` 按媒体课程 ID 列课次，`media export` 按课次 ID 导出 | 课程目录、课次播放入口、下载文件分别对应不同请求 |
| 图书馆资源 | `library holdings` 取书目的逐册馆藏，`library seats list` 取指定区域座号，`library rooms slots` 取指定房间时段 | 可借复本、可选座号、符合时长的空档是三种独立结果 |
| 公告与办理 | `notices show` 按原文 URL 读公开公告，`jw notices show` 按编号读本人教务公告，`service certificate download` 按订单号下载已签发证明 | 公告要注明来源；下载已有证明只产生本地文件 |
| 班车或地铁短驳 | `tongji bus next --from 嘉定 --to 四平 --json` 或 `tongji bus shuttle --line 14 --from 封浜 --json` | 对应方向的计划班次、上车点和校方调整说明。实时车辆位置需要另外的证据 |
| 校医院 | `tongji clinic hours --department "$department" --json` 或 `tongji clinic guide --json` | 指定科室安排或校方挂号流程，保留机构和原指南 |
| 一卡通 | `tongji card balance --json` 或 `tongji card transactions --from "$start" --to "$end" --json` | 本人当前余额或指定区间流水，按用户需要披露相应字段 |

命令简写均以 `tongji` 开头。其他业务的完整参数见下方任务示例。对于续借、提交、预约等写操作，CLI 负责各自的业务校验和回执核对；agent 根据用户的请求决定是否进入写入步骤。

## CLI 已有的固定组合命令

| 快捷命令 | 时间范围 | 固定包含 |
| --- | --- | --- |
| `tongji today --json` | 上海日期今天 | 教务个人排课、Canvas 当天截止的普通作业 |
| `tongji week --json` | 从今天起连续七个上海日期 | 个人排课和普通作业截止项，按日合并 |

“未来七天的课表和到期作业”与 `week` 的覆盖范围一致，一次调用就够了。“下周有哪些待办”涉及不同的日期和事项类型，按下方的日程示例组合。两个快捷命令直接沿用现有 CLI 接口。

## 会话与结果约定

- 沿用环境中的 `TONGJI_BROWSER`。Chrome 和 Chromium 各用自己的校园登录配置。同一配置下的浏览器命令顺序执行，避免争用专用窗口。遇到配置正被占用的提示，等前一条命令结束再查。
- `tongji status --json` 默认检查 Canvas 和教务。单站示例是 `tongji status --site canvas --json`。其余站点名为 `jw`（教务）、`media`（录课）、`service`（一网通办）、`library`（借阅）、`space`（空间预约）、`stadium`（体育）、`card`（一卡通）。公开查询可直接执行。
- 目标站返回 `login_required` 时，用该站的登录命令，如 `tongji login --site canvas --json`。让用户在学校窗口完成认证并等 CLI 自行关闭窗口；`after_restart=authenticated` 表示重开后仍有效。密码、验证码和 Cookie 留在浏览器里。
- 如果终端能查但 agent 在启动浏览器时遇到 `EPERM`，先检查 agent 是否继承同一个浏览器设置，以及沙箱是否允许本次查询启动浏览器、使用临时目录和专用配置。需要授权时，说明要执行的具体命令。这个错误本身无法判断校园登录是否过期。
- 同时读取退出码和 stdout 的 JSON。非零退出时仍可能有可用条目。按来源读取 `status`、`detail`、`items`，有 `sources` 时也检查各子来源。若进程只在 stderr 报错，就报告该错误。

| 读到的结果 | 给用户的答复 |
| --- | --- |
| 查询成功且条目为空 | 说明站点、日期窗口和查询范围，例如“这七天内没有普通作业到期” |
| `week.status=partial`，Canvas 成功、教务需要登录 | 列出已核实的作业，说明这几天的课表暂缺；保留每天缺失的字段 |
| 某字段为 `null`，或课程隐藏总评 | 用“未提供”“提交状态待核实”或“教师隐藏了总评”；保留真正的零分和零条记录 |
| `unverified` 或 `unreachable` | 报告未核实的来源及原因；办理类命令先查回执，避免重复提交 |

## Agent 如何组合任务

下面各节是自然语言任务的处理示例。根据用户给出的对象、日期、输出形式决定需要哪几步。已知对象 ID 时可以直接取详情；从“查一下”进入申请、发送、提交或预约，须有用户对该动作的授权。

### 看未来七天、下一个自然周或全部待办

- **“未来七天课表和作业”**：用固定快捷命令 `tongji week --json`。如用户还关心测验和讨论，再查 `tongji canvas planner --next 7d --json`。相同课程和作业在两边重复出现时合并展示。比较时看课程、条目类型和 ID，保留计划时间与截止时间各自的含义。
- **“下周一到周日，上什么课、有哪些学习安排？”**：以 Asia/Shanghai 算出下周一的 ISO 日期作为 `$start`，查下面两条。课表按教学日组织；planner 按 `scheduled` 选取条目，回答“何时截止”时读 `due`，缺失就说明尚无截止时间。若要穷举一门课程的到期作业，从该课程作业列表按 `due` 筛选目标区间。
- **“还有哪些没做？”**：先确定问的是当周安排、逾期作业，还是包括教学媒体任务。逾期普通作业可直接查 `tongji canvas assignments --overdue --json`。若请求覆盖媒体平台，再查对应学期未完成任务，按平台给出的起止时间筛选。答复写清已查的来源，保留部分成功的结果。

```sh
tongji jw timetable --week next --json
tongji canvas planner --from "$start" --next 7d --json
```

### 查教务安排、申请与公告

“下周哪天有课”可直接查个人课表；“下周是第几教学周”查 `tongji calendar week --json` 并可追加目标日期。多时段或调教室的课保留原表的周次和地点说明。校历标为工作日时，调上哪天的课仍要看排课或调课公告。

| 任务 | 查询顺序 |
| --- | --- |
| 往期课表相关资料 | `tongji calendar terms --json` 取学期全名，再用 `tongji jw courses --term "$term" --json` 查该学期课程。专业课表用 `tongji jw major-timetable --term "$term" --json` |
| 培养要求和个人完成情况 | `tongji jw schemes list --json` 找方案，`tongji jw schemes show "$scheme_id" --json` 读章节；`tongji jw plan --json` 查个人逐门计划，`tongji jw credits --json` 查分类学分 |
| 找课程大纲或授课进度 | `tongji jw syllabus search "$keyword" --json` 查课程代码，再用 `tongji jw syllabus show "$code" --json`；`tongji jw progress list --term "$term" --json` 取得进度记录 ID，再用同学期的 show 查答疑和授课安排 |
| 找通知原文 | 公开通知用 `tongji notices search "$keyword" --pages 3 --json`，再用 `tongji notices show "$url" --json`；教务工作台用 `tongji jw notices list --search "$keyword" --json` 和 `tongji jw notices show "$notice_id" --json` |
| 找本人教务申请或陌生栏目 | `tongji jw applications list --json` 后用 `tongji jw applications show "$number" --json` 看审批进度；`tongji jw menu --search "$keyword" --json` 查本人侧栏可见入口 |

“能不能选这门课”先用 `tongji jw enrollment status --json` 查开放状态，再查 `tongji jw enrollment requests --json` 看个人申请。办理选课、重考或期中退课时核对完整学期和目标教学班的**新课程序号**。按对应命令预览；返回 `closed` 时说明窗口情况，返回 `already` 时说明已有记录。选课办理后查同学期个人课表，期中退课可用 `tongji jw withdrawals --verify "$class_code" --json` 同查退课记录和课表。

例如用户问“公告里讲座改到哪儿了”，先搜与活动相关的标题，再打开原文核对活动名、发布日期和场地。若只有时间得到确认，先给时间和原公告链接，地点写“暂未确认”。检索只覆盖所选来源和页数时，答复也保留这个范围。

### Canvas 课程、作业与反馈

**先确定课程和范围。** 用 `tongji canvas courses --json` 查在读课；查往期课用 `--state completed`，按学期、名称选课程 ID。后续支持该选项的命令也要带上它。小组共享文件、公告和讨论使用 `tongji canvas groups --json` 给出的组 ID 和 `--group`。不同平台的课程 ID 分别从各自目录取得。

**“我有哪些作业？”** 未来七天用 `tongji canvas assignments --next 7d --json`，已过期且明确未提交用 `tongji canvas assignments --overdue --json`。查某门课的全部可见作业用 `tongji canvas assignments --course "$course_id" --json`，可覆盖没有截止日期的作业。要包含测验和讨论则查 `tongji canvas planner --next 7d --json`，回答中区分计划时间和截止时间。

**“上学期这份作业，我交了什么，老师怎么评的？”** 用以下顺序逐步取 ID；用户只问反馈时，读到提交记录就能回答。

```sh
tongji canvas courses --state completed --json
tongji canvas assignments --course "$course_id" --state completed --json
tongji canvas assignment show "$assignment_id" --course "$course_id" --state completed --json
tongji canvas submission "$assignment_id" --course "$course_id" --state completed --history --json
tongji canvas assignment download "$assignment_id" --course "$course_id" --state completed --attachment "$attachment_id" --attempt "$attempt" --output "$new_file" --json
```

附件 ID 取自本人交件或反馈的 `attachment_details`。指定 `--attempt` 可下载对应尝试的交件附件；取反馈附件用默认查询，省略该参数。课程文件另走 `canvas files` 和 `canvas file download`。同名文件用 ID 区分。

**“帮我交这份作业。”** 先从详情确认作业名、课程、允许的提交方式，再核对用户给的文件路径、正文或网址。下面以文件交件为例。

```sh
tongji canvas assignment show "$assignment_id" --course "$course_id" --json
tongji canvas assignment submit "$assignment_id" --course "$course_id" --file "$file" --preview --json
tongji canvas submission "$assignment_id" --course "$course_id" --json
```

文件、文本、网址每次选一种；多个文件可重复给 `--file`。第二条返回 `action=preview` 表示完成预检。用户已明确要求提交且目标一致时，去掉第二条的 `--preview` 执行一次。只有回读到 `action=submitted` 才按返回的尝试次数和时间报告成功。回执待核实时先用第三条查本人记录。

**成绩、测验和沟通。**

| 需求 | 用法与解释 |
| --- | --- |
| 这门课的分数怎么算 | `tongji canvas grades --course "$course_id" --json` 读当前分数及计入未评分项目后的分数；`tongji canvas grading --course "$course_id" --json` 查组权重和舍分规则；`tongji canvas assignment rubric "$assignment_id" --course "$course_id" --json` 查单份作业的量规 |
| 查一次测验的要求或本人尝试 | `tongji canvas quiz list --course "$course_id" --json` 返回 ID 和引擎；新测验用 `tongji canvas quiz submission "$quiz_id" --course "$course_id" --engine new --json` 查本人状态，经典测验用默认引擎。查要求用 show。查询本人尝试不会开始答题 |
| 查讨论或发消息 | `tongji canvas discussions --course "$course_id" --json` 找主题；`tongji canvas discussion show "$topic_id" --course "$course_id" --replies --json` 查回复。私信用 `tongji canvas recipients "$name" --course "$course_id" --json` 区分同名收件人。新消息预览要核对课程、收件人和正文；回复既有会话会发给全部直接收件人。回执不明时先查原会话或已发送文件夹 |

如果用户要给同学发消息，先从课程内搜索结果取得个人 ID，核对对象和正文后走预览：

```sh
tongji canvas conversation send --course "$course_id" --to "$recipient_id" --subject "$subject" --message "$message" --preview --json
tongji canvas inbox --scope sent --json
tongji canvas conversation show "$conversation_id" --json
```

后两条用于核对已发送记录。用户只问“老师说了什么”时，读已有公告、会话或讨论就能回答。同一段文字发给个人、回复整个会话和发表到小组讨论区，接收范围各不相同。

### 讲义、录课和语音稿

“找老师上传的讲义”从 `tongji canvas materials --course "$course_id" --json` 按模块顺序查，文件用 `tongji canvas file download "$file_id" --course "$course_id" --output "$new_file" --json`。往期课程在两步都加 `--state completed`。模块页正文可用目录给出的 slug 查询。

“找某一节的回放，把课件和语音稿发我”从教学媒体平台查。先按课程名或教师找课，再按课次标题、周次和平台状态选一节。

```sh
tongji media courses --search "$keyword" --json
tongji media sessions --course "$media_course_id" --status 回放 --json
tongji media export "$session_id" --course "$media_course_id" --include slides --include transcript --output "$new_docx" --json
```

若只要链接，返回该课次的播放页即可。只要课件时省略 `--include`，输出用新 `.pptx` 路径；含语音原文或译文时用 `.docx`，需要译文再加 `--include translation`。输出目录须已存在，校方提示“暂无课件内容”时保留该结果。任务页另用 `tongji media terms --json` 取媒体平台学期代码，再用 `tongji media tasks --term "$media_term" --kind required --status 未完成 --json` 查必做项。

### 图书馆的书、座位与房间

**借阅。** `tongji library hours "$campus" --json` 查常规开放时间，节假日再核对馆方通知。用 `tongji library search "$keyword" --json` 找书目，再用 `tongji library holdings "$book_id" --json` 查各馆可借复本、索书号和单册状态。本人在借用 `tongji library loans --json`，历史借阅加 `--history`。用户要续借时，从在借记录取条码和原应还日，用 `tongji library renew "$barcode" --due "$due" --preview --json` 核对。同一条码的新应还日晚于原日期才算续借成功。

**普通座位。** 馆方余座需要能访问空间预约系统的网络和该站登录。下面每一步用上一步返回的名称，先查馆区，再查楼层和区域。询问空位只需要前三步。

```sh
tongji library seats availability --date "$day" --json
tongji library seats availability --date "$day" --branch "$branch" --floor "$floor" --json
tongji library seats list --date "$day" --branch "$branch" --floor "$floor" --area "$area" --json
tongji library seats reserve --date "$day" --branch "$branch" --floor "$floor" --area "$area" --time "$slot" --seat "$seat" --preview --json
tongji library reservations --kind seat --json
```

楼层名可先用仅带 `--branch` 的 availability 查询。回答余座时给出日期、馆区、范围和读取时间；具体座号保留前导零。即使有余座，预览仍可能显示按钮倒计时或 `booking_available=false`。正式预约后用最后一条核对地点、座号、日期、时段和馆方状态。

**研修专座和研讨室。** 研修或考研专座按馆方周期查询，`tongji library study availability --json` 查馆舍，`tongji library study list --branch "$branch" --floor "$floor" --area "$area" --period next --json` 查下期的起止日、座号及本人权限。考研座位加 `--type exam`。研讨室按房间和连续时段查询：

```sh
tongji library rooms dates --json
tongji library rooms list --date "$day" --type 多人研讨室 --json
tongji library rooms slots "$room_id" --date "$day" --json
tongji library rooms reserve "$room_id" --date "$day" --time "$slot" --preview --json
tongji library rooms receipts --json
```

从 slots 同时核对开放时段、空档、最短时长及人数上下限。正式申请时由用户在校方窗口填完并提交，再按回车核对回执；向用户照录“待审核”“已通过”等实际状态。

### 办事大厅、证明和表格

- 用户问“在读证明怎么办”，用 `tongji service find 在读证明 --json` 查公开指南和本人可见的门户事项。给出适用人群、步骤及官方入口，说明其中哪些来源可读。
- 用户要办某项业务，按 find 的来源、事项全名和模板核对预览，例如 `tongji service apply "$title" --source portal --template "$template" --preview --json` 适用于旧门户电子证明模板。办理后用 `tongji service applications --with-flow --json` 查本人办件和审批进度。
- 用户要找已经签发的证明，先用 `tongji service certificates --json` 取得本人订单号，再用 `tongji service certificate download "$receipt" --output "$new_pdf" --json` 保存指定 PDF。下载已有证明可直接走这条路径。
- 用户要空白表格，用 `tongji service forms "$keyword" --json` 搜研究生院下载目录，`tongji service form "$url" --json` 看说明和附件。教务学籍管理表格另用 `tongji jw forms list student-status --search "$keyword" --json`。附件名取自详情，输出到用户指定的新文件路径。

### 找自习教室、订体育场地或查宿舍水电

- **教室。** 用 `tongji rooms search "$keyword" --json` 取校方完整教室名，再用 `tongji rooms status "$room_name" --json` 看公开状态。楼栋目录和排课需要学校开放平台授权及 `TONGJI_OPEN_TOKEN`；用排课信息回答时，只能确认计划占用情况。
- **场馆。** 用 `tongji sports venues --campus 四平 --venue 网球 --json` 取场馆名，再用 `tongji sports slots --venue "$venue" --date "$day" --json` 查具体场地和时段。用户只问有哪些场次时即可返回。要下单时先预览金额，由本人在平台完成下单，用 `tongji sports orders --json` 核对新增订单。
- **水电。** `tongji dorm locations --json` 列计量系统，依次加 `--campus`、`--building` 取得楼栋和楼层原名。用 `tongji dorm electricity --meter "$system" "$building" "$floor" "$room" --json` 查指定电表余额；逐日电量用 `dorm usage`，水表用 `dorm water` 和 `dorm water-usage`。保留单位和校方记录时间。缺少本人房间时先补齐位置；省略电表位置的开放平台路径需要另行授权。

## 把结果交还给用户

- **日程**按上海日期列课程、节次、原表地点和作业截止时间。课程有分周地点时保留周次；课程安排有冲突时给出两条来源。普通作业到期数为零，只能回答这个日期窗口内的到期情况。
- **材料**区分页面入口、附件原链接和已下载文件。用户要文件时，在下载或导出成功后核对输出路径和文件大小，给出可打开的文件链接。用户只要官网地址时直接给对应页面。
- **办理**说明当前到了预览、已提交、待审核或已办结哪一步。能取得回执时带上与任务相关的编号或时间。用户问“我的申请通过了吗”，已有申请编号只证明提交过，还要看校方最新审批状态。

其他命令、参数和生产环境验收范围见[仓库 README](https://github.com/TTAWDTT/tongji-cli#readme)。可随时用具体子命令的 `--help` 核对当前安装版本支持的选项。

## 学习通网页版（本地扩展）

- `tongji login --site chaoxing` 由用户在官方窗口认证；`status --site chaoxing --json` 核对登录。
- `tongji chaoxing courses --json` 列出当前机构我学的课；同名多班使用复合 ID。
- `tongji chaoxing assignments --course "课程ID:班级ID" --json` 读取普通作业、提交状态及官方作答时间；省略课程查询当前目录。
- `week` 已包含学习通；每日 `chaoxing_assignments` 是可定位日期的作业，`week.undated_assignments` 是截止时间未知的作业。回答待办时检查两处，不能将未知日期说成本周到期或已逾期。`today` 仅含能确认当天截止的项。
- 只读取普通作业，不含考试和章节测验，不提供学习通提交操作。部分课程失败时保留成功项和错误范围。读取 `due_as_listed` 时保留原文，不补造年份。
