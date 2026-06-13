# AGENTS.md

## 语言与定位

- 默认用中文交流和写项目说明。
- 这个项目后期会由非计算机专业人员维护。代码、界面文案、数据字段和操作流程都要优先保证直观、可读、少绕弯。
- 按上线版标准制作。不要在正式界面里出现测试版语气，例如“API 地址”“测试页面”“用 HTML 做空间树”等开发说明。
- 旧逻辑如果已经和当前产品思路冲突，可以直接删除，不要为了兼容测试数据留下难维护的分支。
- 请求字段以当前前端和正式 API 合同为准；不要保留历史字段、旧别名或双轨兼容分支。迁移时同步更新前端、测试和文档，旧字段直接删除。
- 当前测试阶段保留登录页“测试管理员登录”按钮；正式上线前搜索 `DEV_LOGIN_SHORTCUT` 并删除对应按钮和事件监听。

## 本机环境

- 工作目录：`D:\lab\lab_position`。
- Windows PowerShell 环境。
- Python 优先使用：`C:\programs\miniforge\envs\codex\python.exe`。
- 不建议用 `conda run -n codex python ...` 启动本项目；本机 `conda run` 偶发临时文件占用问题。
- 读取或输出中文时先设置 UTF-8，避免 PowerShell 把中文写成问号或乱码。

## 服务与验证

- 前端默认：`http://127.0.0.1:5173/`。
- 后端默认：`http://127.0.0.1:8000`。
- 如果数据库被占用，可以停掉占用 `8000` 和 `5173` 的服务；只杀对应端口进程，不要误杀 Codex 或其他后台进程。
- 常用检查：
  - `node --check frontend\app.js`
  - `C:\programs\miniforge\envs\codex\python.exe -m py_compile backend\server.py backend\registration.py backend\movements.py backend\storage_api.py`
  - `C:\programs\miniforge\envs\codex\python.exe backend\server.py --check`
- `tests\smoke_test.py` 不作为每次改动的常规检查。它会删除并重建 `db\lab_inventory.sqlite3`，备份恢复耗时较长；只有改到后端核心流程、数据库迁移、导入导出、发布前检查，或用户明确要求时才运行。
- 如果确实运行 `tests\smoke_test.py`，必须先备份当前演示库，运行后恢复；不要因为小的前端/样式/文案调整反复跑完整 smoke。

## 数据库与演示数据

- 当前运行库：`db\lab_inventory.sqlite3`。
- SQLite 主数据和操作记录库保持在同一个数据库文件中；30 人左右课题组使用更容易备份、迁移和排错。
- 测试阶段数据都可以删改，但演示数据也要体现上线版思路，不要继续展示旧模型。
- 当前仍处测试阶段时，如果正式字段合同或 schema 变化较大，可以清空并按最新 `db\schema.sql` 和测试/演示数据脚本重建 `db\lab_inventory.sqlite3`；不要为了旧库保留不一致字段、旧接口或复杂运行期迁移分支。
- 数据库里如果改了空间名称或父子关系，要同步更新库存的 `storage_location` 快照，否则列表里会残留旧路径。
- 写入中文演示数据时要注意编码。必要时用 Python 字符串 Unicode 转义，避免 PowerShell 管道导致中文变成 `?`。

## dev_tools 目录定位

- `dev_tools\` 只用于部署前的临时测试、演示库生成、一次性数据导入或离线迁移辅助。
- 正式部署后，系统日常维护不能依赖 `dev_tools\` 里的脚本；管理员应通过正式界面、后端正式接口或服务器计划任务完成维护。
- 需要上线后持续使用的能力，例如数据库备份、数据健康检查、Excel 导入预检，必须进入 `backend\` 正式模块和管理员界面，不要放在 `dev_tools\` 作为运行时维护入口。
- 部署包默认不应包含 `dev_tools\`，除非本次部署明确要在上线前执行一次性导入，并且执行后不作为系统依赖保留。

## 空间管理核心思路

- 冰箱、柜子、液氮罐、架子、抽屉、样本架都按统一的“空间框架”管理。
- 每个非盒子空间都可以有 `rows`、`cols`，表示它容纳下级空间的行列框架。
- 下级空间用 `grid_row`、`grid_col` 表示放在父级空间第几行第几列。
- 下级空间或盒子没有 `grid_row` / `grid_col` 时，视为放在父级空间的未指定格位区，不自动占用框架格位。
- 空间概览左侧提供虚拟“未归位”入口，用于承接还没有指定具体空间的已入库试剂和标本；新建、到货、分管或移动如果没有指定存放空间，保存为 `storage_node_id = NULL`。
- “未归位”不是 `storage_nodes` 里的真实系统空间。数据库里不要创建 `UNPLACED_LOCATION` / `DISCARDED_LOCATION` 节点，也不保留这类旧系统空间的迁移识别逻辑。
- 虚拟“未归位”只显示 `storage_node_id IS NULL` 且状态为可用或停用的对象；已订购试剂、已耗尽试剂和已耗尽标本不显示在这里。
- 盒子是同一思路的特殊末端空间：盒子有固定孔位，试剂和标本才使用 `position_in_box`。
- 不再使用冰箱专属的“上层/下层”自动生成逻辑。冰箱下面可以放样本架、抽屉、盒子或其他空间，靠统一网格表达。
- 后端应保持规则简单：只有 `box` 支持孔位；非盒子空间移动库存时位置就是空间本身。
- 空间维护应能创建所有 `node_type`，不要只支持新建冰箱和盒子。
- 空间移动也要写入 `movements`，方便误移动回滚和后续追溯。

## 界面设计约定

- 空间目录和格子里不要反复显示长类型标签，例如“实验室/研究所”“冰箱/柜子/液氮罐”。这些只在空间编辑表单里需要。
- 空间目录优先显示：空间名称、直接父级、库存数量。
- 空间框架格子优先显示：格位、下级空间名称、件数；未指定格位的下级空间和库存显示在当前空间的未指定格位区。
- 盒内孔位优先显示：孔位、试剂或标本编号、名称。
- 孔位格不能为了适配屏幕被压到不可读。宁可横向滚动，也不要把字体压小或隐藏重要信息。
- 移动端也要保留孔位中的核心信息，不能直接隐藏试剂名称。
- 页面要减少重复入口。试剂订购、到货、验证登记合并在“试剂登记”；管理员能力合并在“管理员”选项卡。
- 移动端弹窗、下拉菜单和空间维护菜单必须限制在可视区域内，不能出页面。

## 前端维护要点

- 前端不用打包器，按普通 `<script>` 顺序加载。新增文件前先确认是否能放进现有业务模块，避免拆太碎。
- 主要结构：
  - `frontend\core.js`：全局状态、API、表单工具、提示。
  - `frontend\ui-common.js`：表格、下拉、通用列定义、空间选择公共函数。
  - `frontend\inventory-ui.js`：空间概览、盒内孔位、位置选择器的纯渲染函数。
  - `frontend\registration-page.js`：订购登记、到货、验证、临床标本入库、分管、流转记录。
  - `frontend\inventory-page.js`：库存概览、库存移动、空间维护、库存明细。
  - `frontend\admin-page.js`：Excel 导入导出、用户管理、下拉配置。
  - `frontend\app.js`：登录、导航、事件绑定、页面入口，不放大段业务 SQL/表格逻辑。
- 样式里 `.frame-grid` / `.frame-cell` 负责普通空间框架，`.well-grid` / `.well` 负责盒内孔位。
- 不要重新引入 `.freezer-frame`、`.freezer-layer` 这类冰箱专属旧样式。
- 临床标本只使用 `amount` / `amount_unit` 表示重量或体积，不再增加数量/单位两套字段。

## 后端维护要点

- 后端按少数业务模块组织，不要回到一个大文件，也不要拆成十几个十几行的小文件。
- 主要结构：
  - `backend\server.py`：HTTP 路由、权限检查、启动入口；路由按库存、登记流转、空间、管理员分组。
  - `backend\database.py`：SQLite 连接、建表迁移、默认管理员和默认根空间。
  - `backend\auth.py`：登录、密码哈希、令牌、改密码。
  - `backend\reagents.py`：试剂列表、详情、新增、编辑、特殊关注、总览指标。
  - `backend\registration.py`：订购登记、到货、验证登记、验证图片上传与压缩。
  - `backend\movements.py`：试剂、临床标本和空间移动，出库登记，误操作回滚。
  - `backend\clinical_samples.py`：临床标本入库、查询、详情。
  - `backend\storage_api.py`：空间树、空间可视化、空间节点新增/编辑/删除。
  - `backend\storage_inventory.py`：空间路径、孔位占用、位置分配、耗尽释放等库存规则。
  - `backend\admin.py`：用户管理、Excel 导入导出、下拉配置。
  - `backend\options_config.py`：读取和保存 `config\dropdown_options.json` 中的常改下拉选项。
  - `backend\constants.py`：角色、空间类型和盒子规格等结构性常量。
  - `backend\common.py`：通用错误、时间、行转换、审计。
- 试剂“已耗尽”或数量归零时，只释放 `storage_node_id`、`storage_location`、`box_id`、`position_in_box`，不要删除 `reagents` 行，也不要删除 `validations` 行。
- 试剂状态只保留 `已订购`、`可用`、`停用`、`已耗尽`；`已订购` 表示未形成实物库存，`可用` 和 `停用` 都按仍占位置的实物处理，`已耗尽` 由出库或数量归零触发并释放位置。
- 验证记录仍选择具体试剂，但 `validations.catalog_no` 要保存当时关联的货号；历史记录和详情展示优先用该快照，旧记录可从试剂表货号兜底显示。
- 验证图片上传支持 `png`、`jpg/jpeg`、`webp`、`tif/tiff` 源文件，后端统一转成 `.jpg` 保存，目标 1MB 以内。
- 临床标本用独立表 `clinical_samples`，不记录个人信息；编号前缀默认 `SMP`，可以手动改；和试剂尽量使用同一套字段名：`code`、`source_code`、`name`、`category`、`amount`、`amount_unit`、`quantity`、状态和存放位置。
- 临床标本状态只保留 `可用`、`停用`、`已耗尽`；`停用` 只是标识，和 `可用` 一样继续占用位置并可移动/出库，出库后统一变成 `已耗尽`。
- 耗尽释放位置要写入 `movements`，`to_location` 用“未放置（已耗尽）”，方便之后追溯实物从哪里拿出。
- 移动回滚必须校验对象仍在该条移动记录的新位置；目标孔位或格位已占用时不能覆盖。
- `storage_nodes` 的关键字段：`node_type`、`rows`、`cols`、`grid_row`、`grid_col`、`parent_id`。
- 统一空间网格相关函数：`grid_label`、`grid_position`、`assign_grid_positions`、`default_grid_for_node`、`clean_node_dimension`。
- `storage_visual` 是前端空间概览的数据来源。修改空间结构前后都要重点检查它返回的 `grid`、`children`、`wells`。
- “未归位”是 `storage_visual` 返回给前端的虚拟视图节点，前端用 `node_id=-1` 选择它；表单、拖拽和移动接口写入时仍使用空值/`NULL`。
- 保持后端规则直白，优先用少量清晰函数表达业务，不要堆历史兼容分支。

## 测试与浏览器确认

- 代码检查通过不代表界面好用。涉及前端或空间布局时，要打开 `http://127.0.0.1:5173/` 实际确认。
- 浏览器确认做关键路径抽查即可，优先验证本次改动直接影响的 1-2 个入口和控制台错误，不要把相邻功能全量点一遍导致耗时过长。
- 小改动优先用 `node --check`、`py_compile`、`backend\server.py --check` 和浏览器关键路径确认；不要默认升级为完整 smoke。
- 必查场景：
  - 根空间显示为横向空间框架。
  - 冰箱显示为行列框架，不出现上层/下层专属界面。
  - 样本架/抽屉显示为同一套框架。
  - 盒子显示孔位，并能看到试剂或标本编号和名称。
  - 空间维护可以编辑类型、行列、父级行列位置。
  - 流转记录可以显示移动、出库和回滚记录，回滚列不要过宽。
  - 手机端空间维护等菜单不能超出页面。
- 浏览器控制台不能有明显错误。
