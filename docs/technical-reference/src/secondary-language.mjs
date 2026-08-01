export const secondaryLanguageMeta = {
  ja: { html: "ja", label: "日本語", dir: "ltr" },
  zh: { html: "zh-Hans", label: "中文", dir: "ltr" },
  es: { html: "es", label: "Español", dir: "ltr" },
  it: { html: "it", label: "Italiano", dir: "ltr" },
  ar: { html: "ar", label: "العربية", dir: "rtl" },
};

// Japanese remains the authored secondary-language source. Every record is
// published with reviewed static translations; the browser never calls a
// translation service and never changes the English primary copy.
export const secondaryTranslations = [
  ["BSC TestnetはChain ID 97、TRON Shastaはnetwork identifier「tron-shasta」で識別します。 Solidityのコンパイル成功だけではTRON TVM互換性を証明しません。経路有効化前に対象チェーンでの検証を必須とします。",
    "BSC测试网使用Chain ID 97，TRON Shasta使用网络标识符“tron-shasta”。仅成功编译Solidity并不能证明TRON TVM兼容性；启用路径前必须在目标链上完成验证。",
    "BSC Testnet se identifica con Chain ID 97 y TRON Shasta con el identificador «tron-shasta». Compilar Solidity correctamente no demuestra compatibilidad con TRON TVM; la validación en la cadena de destino es obligatoria antes de habilitar una ruta.",
    "BSC Testnet è identificata dal Chain ID 97 e TRON Shasta dall’identificatore «tron-shasta». La corretta compilazione Solidity non prova la compatibilità con TRON TVM; prima di abilitare una rotta è obbligatoria la verifica sulla chain di destinazione.",
    "تُعرّف شبكة BSC الاختبارية بمعرّف السلسلة 97، وتُعرّف TRON Shasta بمعرّف الشبكة «tron-shasta». نجاح ترجمة Solidity وحده لا يثبت التوافق مع TRON TVM؛ ويجب التحقق على السلسلة المستهدفة قبل تفعيل أي مسار."],
  ["Chain ID、RPC、Currency Symbolの公開後にWalletへ登録します。", "在Chain ID、RPC和货币符号公布后再添加到钱包。", "Añádala al wallet después de publicar Chain ID, RPC y símbolo de moneda.", "Registrarla nel wallet dopo la pubblicazione di Chain ID, RPC e simbolo della valuta.", "تُضاف إلى المحفظة بعد نشر معرّف السلسلة وRPC ورمز العملة."],
  ["Chain IDとGenesisをProofへ拘束", "将Chain ID和创世状态绑定到证明", "Vincular Chain ID y génesis a la prueba", "Vincolare Chain ID e genesi alla prova", "ربط معرّف السلسلة وكتلة التكوين بالإثبات"],
  ["Compiler、Dependency、Source Commit、Deployment Evidenceを固定します。", "固定编译器、依赖项、源代码提交和部署证据。", "Fijar compilador, dependencias, commit de origen y evidencia de despliegue.", "Fissare compilatore, dipendenze, commit sorgente ed evidenze di deployment.", "تثبيت المترجم والاعتماديات والتزام المصدر وأدلة النشر."],
  ["ERC・BSC・TRON連携", "ERC、BSC与TRON集成", "Integración ERC, BSC y TRON", "Integrazione ERC, BSC e TRON", "تكامل ERC وBSC وTRON"],
  ["Ethereum／ERC・BSC・TRON相互運用経路。", "Ethereum/ERC、BSC与TRON互操作路径。", "Rutas de interoperabilidad Ethereum/ERC, BSC y TRON.", "Rotte di interoperabilità Ethereum/ERC, BSC e TRON.", "مسارات التشغيل البيني مع Ethereum/ERC وBSC وTRON."],
  ["Ethereumトークン標準", "Ethereum代币标准", "Estándar de tokens de Ethereum", "Standard token Ethereum", "معيار رموز Ethereum"],
  ["JUNCA Social Ecosystem Chainは、制度的アプリケーション、デジタル資産、相互運用サービスを支える、 アクセス・アイデンティティ・価値循環の信頼基盤です。プロトコル統制、ネットワーク運用、 パートナー資産管理、独立証跡を明確に分離します。",
    "JUNCA Social Ecosystem Chain是支持机构应用、数字资产和互操作服务的访问、身份与价值流通信任基础。它明确分离协议治理、网络运营、合作伙伴资产管理和独立证据。",
    "JUNCA Social Ecosystem Chain es una base de confianza para acceso, identidad y circulación de valor que respalda aplicaciones institucionales, activos digitales y servicios interoperables. Separa claramente la gobernanza del protocolo, la operación de red, la administración de activos de socios y la evidencia independiente.",
    "JUNCA Social Ecosystem Chain è una base di fiducia per accesso, identità e circolazione del valore a supporto di applicazioni istituzionali, asset digitali e servizi interoperabili. Separa chiaramente governance del protocollo, operazioni di rete, amministrazione degli asset dei partner ed evidenze indipendenti.",
    "تمثل JUNCA Social Ecosystem Chain أساس ثقة للوصول والهوية وتداول القيمة، وتدعم التطبيقات المؤسسية والأصول الرقمية والخدمات القابلة للتشغيل البيني. وهي تفصل بوضوح بين حوكمة البروتوكول وتشغيل الشبكة وإدارة أصول الشركاء والأدلة المستقلة."],
  ["JUNCA Social Ecosystem Chainは、同期対象のBlock Rangeを認証済みFinality証跡と照合します。現行Sourceは、Trusted Checkpoint Anchor、Canonical Persisted State、Authenticated Peer Frame、Live Runtime Evidence Bundleも受入前に検証します。各ProofはChain Identity、Block Height、Round、Block Hash、Active Validator Set Hashへ拘束されます。重複Validator、未知Validator、不正署名を拒否し、Finality Certificateの成立には厳格な3分の2超のVoting Powerを必要とします。",
    "JUNCA Social Ecosystem Chain将同步区块范围与经认证的终局性证据进行核对。当前源代码还会在验收前验证可信检查点锚、规范持久状态、已认证对等帧和实时运行证据包。每项证明均绑定链身份、区块高度、轮次、区块哈希和有效验证者集合哈希。系统拒绝重复、未知或无效的验证者签名，终局性证书必须获得严格超过三分之二的投票权。",
    "JUNCA Social Ecosystem Chain contrasta los rangos de bloques sincronizados con evidencia de finalidad certificada. El código actual también valida, antes de la aceptación, anclas de puntos de control confiables, estado canónico persistido, tramas de pares autenticadas y paquetes de evidencia del runtime en vivo. Cada prueba queda vinculada a identidad de cadena, altura, ronda, hash de bloque y hash del conjunto validador activo. Se rechazan validadores duplicados o desconocidos y firmas inválidas; un certificado de finalidad exige estrictamente más de dos tercios del poder de voto.",
    "JUNCA Social Ecosystem Chain confronta gli intervalli di blocchi sincronizzati con evidenze di finalità certificata. Il sorgente corrente verifica inoltre, prima dell’accettazione, anchor di checkpoint attendibili, stato canonico persistito, frame peer autenticati e bundle di evidenze del runtime live. Ogni prova è vincolata a identità della chain, altezza del blocco, round, hash del blocco e hash del set di validatori attivo. Validatori duplicati o sconosciuti e firme non valide vengono respinti; un certificato di finalità richiede rigorosamente oltre due terzi del potere di voto.",
    "تطابق JUNCA Social Ecosystem Chain نطاقات الكتل المتزامنة مع أدلة النهائية المعتمدة. كما يتحقق المصدر الحالي، قبل القبول، من نقاط الارتكاز الموثوقة والحالة المعيارية المحفوظة وإطارات الأقران المصادق عليها وحزم أدلة وقت التشغيل الحية. يُربط كل إثبات بهوية السلسلة وارتفاع الكتلة والجولة وتجزئة الكتلة وتجزئة مجموعة المدققين النشطة. تُرفض التوقيعات المكررة أو المجهولة أو غير الصالحة، وتتطلب شهادة النهائية أكثر من ثلثي قوة التصويت بشكل صارم."],
  ["JUNCAのプロトコル公開、発行、運用統制責任を示す承認済み対外表記。", "用于说明JUNCA协议发布、发行和运营治理责任的已批准公开表述。", "Declaración pública aprobada que identifica la responsabilidad sobre publicación, emisión y control operativo del protocolo JUNCA.", "Dicitura pubblica approvata che identifica la responsabilità per pubblicazione, emissione e controllo operativo del protocollo JUNCA.", "صياغة عامة معتمدة توضح مسؤولية نشر بروتوكول JUNCA وإصداره وضبط تشغيله."],
  ["Metadata、権利、Storage、Integrity Digest、Migrationを定義します。", "定义元数据、权利、存储、完整性摘要和迁移。", "Definir metadatos, derechos, almacenamiento, resumen de integridad y migración.", "Definire metadati, diritti, storage, digest di integrità e migrazione.", "تعريف البيانات الوصفية والحقوق والتخزين وملخص السلامة والترحيل."],
  ["Negative Test、権限、秘密情報、Incident Routeを監査します。", "审计负向测试、权限、机密信息和事件响应路径。", "Auditar pruebas negativas, permisos, secretos y rutas de incidentes.", "Verificare test negativi, autorizzazioni, segreti e percorsi di incidente.", "تدقيق الاختبارات السلبية والصلاحيات والأسرار ومسارات الحوادث."],
  ["NFT・デジタル資産", "NFT与数字资产", "NFT y activos digitales", "NFT e asset digitali", "الرموز غير القابلة للاستبدال والأصول الرقمية"],
  ["Test Asset Separation、Rate Limit、Abuse Controlを前提に公開します。", "仅在测试资产隔离、速率限制和滥用控制条件下公开。", "Publicar con separación de activos de prueba, límites de tasa y controles contra abusos.", "Pubblicare con separazione degli asset di test, rate limit e controlli antiabuso.", "يُنشر مع فصل أصول الاختبار وحدود المعدل وضوابط إساءة الاستخدام."],
  ["Owner、Mint、Burn、Pause、Treasury、Upgradeの権限を分離します。", "分离所有者、铸造、销毁、暂停、金库和升级权限。", "Separar los permisos de propietario, acuñación, quema, pausa, tesorería y actualización.", "Separare i permessi di owner, mint, burn, pausa, tesoreria e upgrade.", "فصل صلاحيات المالك والسك والحرق والإيقاف والخزانة والترقية."],
  ["Runtime Binding完了後に正本Repositoryから提供します。", "完成运行时绑定后从规范仓库提供。", "Se suministra desde el repositorio canónico tras completar la vinculación del runtime.", "Fornito dal repository canonico dopo il completamento del binding del runtime.", "يُقدَّم من المستودع المعياري بعد اكتمال ربط وقت التشغيل."],
  ["Source VerificationとRPC／Explorer Parityを記録します。", "记录源代码验证及RPC/Explorer一致性。", "Registrar la verificación del código y la paridad RPC/Explorer.", "Registrare la verifica del sorgente e la parità RPC/Explorer.", "تسجيل التحقق من المصدر وتكافؤ RPC والمستكشف."],
  ["Supply、Mint、Burn、Pause、Treasury権限を分離して検証します。", "分离并验证供应、铸造、销毁、暂停和金库权限。", "Separar y verificar los permisos de suministro, acuñación, quema, pausa y tesorería.", "Separare e verificare i permessi di supply, mint, burn, pausa e tesoreria.", "فصل صلاحيات الإمداد والسك والحرق والإيقاف والخزانة والتحقق منها."],
  ["Testnet Evidence、監査、運用、Release Approvalを一つのPacketにします。", "将测试网证据、审计、运营和发布批准汇集为一个数据包。", "Reunir evidencia de Testnet, auditoría, operación y aprobación de release en un único paquete.", "Riunire evidenze Testnet, audit, operazioni e approvazione del rilascio in un unico pacchetto.", "جمع أدلة شبكة الاختبار والتدقيق والتشغيل وموافقة الإصدار في حزمة واحدة."],
  ["Validator Set変更をBlock Heightへ拘束", "将验证者集合变更绑定到区块高度", "Vincular los cambios del conjunto validador a la altura de bloque", "Vincolare le modifiche del set di validatori all’altezza del blocco", "ربط تغييرات مجموعة المدققين بارتفاع الكتلة"],
  ["アーキテクチャ、実装、証跡の順に、技術判断へ必要な情報へ到達する。", "按照架构、实现、证据的顺序获取技术决策所需信息。", "Acceda a la información para decisiones técnicas en el orden: arquitectura, implementación y evidencia.", "Accedi alle informazioni per le decisioni tecniche nell’ordine: architettura, implementazione ed evidenze.", "الوصول إلى معلومات القرار التقني بالترتيب: البنية ثم التنفيذ ثم الأدلة."],
  ["ガバナンス・セキュリティ", "治理与安全", "Gobernanza y seguridad", "Governance e sicurezza", "الحوكمة والأمن"],
  ["ガバナンス・責任分界", "治理与责任边界", "Gobernanza y responsabilidades", "Governance e responsabilità", "الحوكمة وحدود المسؤولية"],
  ["ガバナンス各章", "治理章节", "Capítulos de gobernanza", "Capitoli di governance", "فصول الحوكمة"],
  ["クロスネットワーク経路とリリース統制", "跨网络路径与发布控制", "Rutas entre redes y control de releases", "Rotte cross-network e controllo dei rilasci", "مسارات الشبكات المتقاطعة وضبط الإصدار"],
  ["クロスネットワーク処理の実行前に必要な独立検証済みRelayer署名の最小数。", "执行跨网络处理前所需的独立验证中继者签名最小数量。", "Número mínimo de firmas de relayers verificadas de forma independiente antes de ejecutar procesos entre redes.", "Numero minimo di firme di relayer verificate in modo indipendente prima di eseguire operazioni cross-network.", "الحد الأدنى من توقيعات المرحّلين المتحقق منها بصورة مستقلة قبل تنفيذ المعالجة عبر الشبكات."],
  ["この章の根拠資料・仕様・検証記録", "本章的依据资料、规范与验证记录", "Fuentes, especificaciones y registros de verificación de este capítulo", "Fonti, specifiche e registri di verifica di questo capitolo", "مصادر هذا الفصل ومواصفاته وسجلات التحقق"],
  ["セキュリティ・リスク", "安全与风险", "Seguridad y riesgos", "Sicurezza e rischi", "الأمن والمخاطر"],
  ["セキュリティ方針", "安全策略", "Política de seguridad", "Policy di sicurezza", "سياسة الأمن"],
  ["デジタル資産の供給、発行、停止、所有権、運用方針に対する制度的統制。", "对数字资产供应、发行、暂停、所有权和运营政策的机构治理。", "Control institucional sobre suministro, emisión, pausa, propiedad y política operativa de activos digitales.", "Controllo istituzionale su supply, emissione, sospensione, proprietà e policy operativa degli asset digitali.", "ضبط مؤسسي لإمداد الأصول الرقمية وإصدارها وإيقافها وملكيتها وسياسة تشغيلها."],
  ["デジタル資産実装正本", "数字资产实现规范源", "Fuente canónica de implementación de activos digitales", "Fonte canonica dell’implementazione degli asset digitali", "المصدر المعياري لتنفيذ الأصول الرقمية"],
  ["本Public Testnetがプロトコル検証環境であり、テスト資産をMainnet発行のJSECと区分することを示す公開表示。", "用于说明本Public Testnet是协议验证环境，并将测试资产与Mainnet发行的JSEC区分开的公开标识。", "Aviso público que identifica esta Public Testnet como entorno de validación del protocolo y separa los activos de prueba del JSEC emitido en Mainnet.", "Avviso pubblico che identifica questa Public Testnet come ambiente di validazione del protocollo e separa gli asset di test dal JSEC emesso su Mainnet.", "إشعار عام يوضح أن شبكة Public Testnet هذه بيئة للتحقق من البروتوكول، ويفصل أصول الاختبار عن JSEC الصادر على Mainnet."],
  ["トークン・NFT・デジタル資産アーキテクチャ", "代币、NFT与数字资产架构", "Arquitectura de tokens, NFT y activos digitales", "Architettura di token, NFT e asset digitali", "بنية الرموز والرموز غير القابلة للاستبدال والأصول الرقمية"],
  ["トークン設計・発行", "代币设计与发行", "Diseño y emisión de tokens", "Progettazione ed emissione di token", "تصميم الرموز وإصدارها"],
  ["ネットワーク接続・コントラクト実装・検証体系。", "网络连接、合约实现与验证体系。", "Conexión de red, implementación de contratos y sistema de verificación.", "Connessione di rete, implementazione dei contratti e sistema di verifica.", "اتصال الشبكة وتنفيذ العقود ومنظومة التحقق."],
  ["ネットワーク接続・検証", "网络连接与验证", "Conexión y verificación de red", "Connessione e verifica della rete", "اتصال الشبكة والتحقق"],
  ["プロトコル・アーキテクチャ／資産標準／相互運用／制度的ガバナンス", "协议架构／资产标准／互操作性／机构治理", "Arquitectura del protocolo / estándares de activos / interoperabilidad / gobernanza institucional", "Architettura del protocollo / standard degli asset / interoperabilità / governance istituzionale", "بنية البروتوكول / معايير الأصول / التشغيل البيني / الحوكمة المؤسسية"],
  ["プロトコル、デジタル資産、相互運用、実装、制度的責任を一つの体系として整理した公式技術書。", "将协议、数字资产、互操作性、实现和机构责任整合为一个体系的官方技术文档。", "Referencia técnica oficial que organiza protocolo, activos digitales, interoperabilidad, implementación y responsabilidad institucional en un único sistema.", "Riferimento tecnico ufficiale che organizza protocollo, asset digitali, interoperabilità, implementazione e responsabilità istituzionale in un unico sistema.", "مرجع تقني رسمي ينظم البروتوكول والأصول الرقمية والتشغيل البيني والتنفيذ والمسؤولية المؤسسية ضمن منظومة واحدة."],
  ["プロトコル各章", "协议章节", "Capítulos del protocolo", "Capitoli del protocollo", "فصول البروتوكول"],
  ["プロトコル基盤", "协议基础", "Base del protocolo", "Base del protocollo", "أساس البروتوكول"],
  ["プロトコル実装正本", "协议实现规范源", "Fuente canónica de implementación del protocolo", "Fonte canonica dell’implementazione del protocollo", "المصدر المعياري لتنفيذ البروتوكول"],
  ["プロトコル範囲", "协议范围", "Alcance del protocolo", "Ambito del protocollo", "نطاق البروتوكول"],
  ["プロトコル範囲と機能・実装状態", "协议范围及功能与实现状态", "Alcance del protocolo y estado funcional y de implementación", "Ambito del protocollo e stato di funzioni e implementazione", "نطاق البروتوكول وحالة الوظائف والتنفيذ"],
  ["メッセージ、送信元取引、Nonceの重複実行を防止する統制。", "防止消息、源交易和随机数被重复执行的控制。", "Control que impide la ejecución duplicada de mensajes, transacciones de origen y nonces.", "Controllo che impedisce l’esecuzione duplicata di messaggi, transazioni sorgente e nonce.", "ضابط يمنع التنفيذ المكرر للرسائل ومعاملات المصدر وقيم Nonce."],
  ["ユースケース設計", "用例设计", "Diseño de casos de uso", "Progettazione dei casi d’uso", "تصميم حالات الاستخدام"],
  ["リスク、統制、必要証跡を一体で設計する。", "将风险、控制和所需证据作为整体进行设计。", "Diseñar conjuntamente riesgos, controles y evidencia requerida.", "Progettare insieme rischi, controlli ed evidenze necessarie.", "تصميم المخاطر والضوابط والأدلة المطلوبة كوحدة واحدة."],
  ["外部パートナーが発行・運用する資産の経済価値、流動性、法的分類、規制適合性を保証するものではありません。", "不保证外部合作伙伴发行或运营资产的经济价值、流动性、法律分类或监管合规性。", "No garantiza el valor económico, la liquidez, la clasificación jurídica ni el cumplimiento regulatorio de activos emitidos u operados por socios externos.", "Non garantisce valore economico, liquidità, classificazione giuridica o conformità normativa degli asset emessi o gestiti da partner esterni.", "لا يضمن القيمة الاقتصادية أو السيولة أو التصنيف القانوني أو الامتثال التنظيمي للأصول التي يصدرها أو يديرها شركاء خارجيون."],
  ["確定・目標・未検証・停止条件を分離する。", "分离已确认、目标、未验证和停止条件。", "Separar estados confirmados, objetivos, no verificados y condiciones de parada.", "Separare stati confermati, obiettivi, non verificati e condizioni di arresto.", "فصل الحالات المؤكدة والأهداف وغير المتحقق منها وشروط التوقف."],
  ["完成時のプロトコル・アーキテクチャ。", "完成态协议架构。", "Arquitectura del protocolo en su estado completo.", "Architettura del protocollo nello stato completo.", "بنية البروتوكول في حالته المكتملة."],
  ["企業導入工程", "企业采用流程", "Proceso de adopción empresarial", "Percorso di adozione aziendale", "مسار التبني المؤسسي"],
  ["機械判定可能なリリース準備状態。", "可由机器判定的发布准备状态。", "Estado de preparación para release evaluable por máquina.", "Stato di preparazione al rilascio valutabile automaticamente.", "حالة جاهزية للإصدار قابلة للتقييم آليًا."],
  ["機能・実装状態", "功能与实现状态", "Estado funcional y de implementación", "Stato di funzioni e implementazione", "حالة الوظائف والتنفيذ"],
  ["機能体系と完成条件。", "功能体系与完成条件。", "Sistema funcional y criterios de finalización.", "Sistema funzionale e criteri di completamento.", "منظومة الوظائف ومعايير الاكتمال."],
  ["技術書トップ", "技术文档首页", "Inicio de la referencia técnica", "Home del riferimento tecnico", "الرئيسية للمرجع التقني"],
  ["技術正本・標準・受入証跡", "技术规范源、标准与验收证据", "Fuente técnica canónica, estándares y evidencia de aceptación", "Fonte tecnica canonica, standard ed evidenze di accettazione", "المصدر التقني المعياري والمعايير وأدلة القبول"],
  ["技術用語集", "技术术语表", "Glosario técnico", "Glossario tecnico", "مسرد تقني"],
  ["旧EpochのValidator Proofを拒否", "拒绝旧纪元的验证者证明", "Rechazar pruebas de validadores de épocas anteriores", "Rifiutare le prove dei validatori di epoche precedenti", "رفض إثباتات المدققين من الحقب القديمة"],
  ["供給・権限・トレジャリー統制。", "供应、权限与金库控制。", "Controles de suministro, autoridad y tesorería.", "Controlli di supply, autorità e tesoreria.", "ضوابط الإمداد والصلاحيات والخزانة."],
  ["経路の公開状態", "路径公开状态", "Estado de publicación de rutas", "Stato di pubblicazione delle rotte", "حالة نشر المسارات"],
  ["現在の検証状態", "当前验证状态", "Estado de verificación actual", "Stato di verifica corrente", "حالة التحقق الحالية"],
  ["公開許可Methodと禁止Methodを分離し、管理系RPCを公開しません。", "分离允许公开和禁止的方法，且不公开管理类RPC。", "Separar métodos públicos permitidos y prohibidos, sin exponer RPC administrativos.", "Separare i metodi pubblici consentiti da quelli vietati, senza esporre RPC amministrativi.", "فصل الأساليب العامة المسموح بها عن المحظورة وعدم كشف واجهات RPC الإدارية."],
  ["参照・受入判定", "参考与验收判定", "Referencia y aceptación", "Riferimenti e accettazione", "المرجع وقرار القبول"],
  ["試験・受入記録", "测试与验收记录", "Registros de pruebas y aceptación", "Registri di test e accettazione", "سجلات الاختبار والقبول"],
  ["資産・証明・サービスの適用構造。", "资产、证明与服务的应用结构。", "Estructura aplicada de activos, pruebas y servicios.", "Struttura applicativa di asset, prove e servizi.", "هيكل تطبيق الأصول والإثباتات والخدمات."],
  ["資産アーキテクチャ", "资产架构", "Arquitectura de activos", "Architettura degli asset", "بنية الأصول"],
  ["自動QA 400件すべてPASS", "全部400项自动QA通过", "Las 400 comprobaciones automatizadas de QA han pasado", "Tutti i 400 controlli QA automatici sono superati", "اجتازت جميع فحوص ضمان الجودة الآلية وعددها 400"],
  ["識別性・来歴・メタデータ永続性。", "可识别性、来源与元数据持久性。", "Identificabilidad, procedencia y persistencia de metadatos.", "Identificabilità, provenienza e persistenza dei metadati.", "قابلية التعريف والمصدر واستمرارية البيانات الوصفية."],
  ["実装・導入", "实现与采用", "Implementación y adopción", "Implementazione e adozione", "التنفيذ والتبني"],
  ["実装済みのChain Coreと、実環境での受入が必要なRuntimeを分離して表示します。", "分别显示已实现的Chain Core与仍需在真实环境中验收的Runtime。", "Se muestran por separado el Chain Core implementado y el Runtime que requiere aceptación en un entorno real.", "Vengono mostrati separatamente il Chain Core implementato e il Runtime che richiede accettazione in un ambiente reale.", "يُعرض Chain Core المنفذ منفصلًا عن Runtime الذي يتطلب قبولًا في بيئة فعلية."],
  ["実測済みの運用証跡を、推測を加えずに表示します。", "展示实测运营证据，不添加推测。", "Se muestra evidencia operativa medida, sin añadir inferencias.", "Mostriamo evidenze operative misurate, senza aggiungere deduzioni.", "تُعرض الأدلة التشغيلية المقاسة من دون إضافة استنتاجات."],
  ["正規開発基盤と補助ゲートウェイを明確に分離して表示します。", "明确区分规范开发基础与辅助网关。", "Se distinguen claramente la base canónica de desarrollo y el gateway auxiliar.", "La base canonica di sviluppo e il gateway ausiliario sono mostrati separatamente.", "يُعرض أساس التطوير المعياري منفصلًا بوضوح عن البوابة المساعدة."],
  ["再現可能なブロックチェーン開発環境を正規基盤としてmainへ統合済みです。", "可复现的区块链开发环境已作为规范基础合并至main。", "El entorno reproducible de desarrollo blockchain se ha integrado en main como base canónica.", "L’ambiente riproducibile di sviluppo blockchain è stato integrato in main come base canonica.", "دُمجت بيئة تطوير البلوك تشين القابلة للتكرار في main بوصفها الأساس المعياري."],
  ["Custom GPT Gatewayは補助機能であり、未統合・未配置・未登録です。", "Custom GPT Gateway是辅助功能，尚未合并、部署或注册。", "Custom GPT Gateway es una función auxiliar; no está integrado, desplegado ni registrado.", "Custom GPT Gateway è una funzione ausiliaria; non è integrato, distribuito né registrato.", "بوابة Custom GPT وظيفة مساعدة؛ وهي غير مدمجة وغير منشورة وغير مسجلة."],
  ["開発環境CIの検証証跡を確認済み", "已确认开发环境CI验证证据", "Evidencia de verificación del CI del entorno de desarrollo confirmada", "Evidenze di verifica CI dell’ambiente di sviluppo confermate", "تم تأكيد أدلة تحقق CI لبيئة التطوير"],
  ["実装正本", "实现规范源", "Fuente canónica de implementación", "Fonte canonica dell’implementazione", "المصدر المعياري للتنفيذ"],
  ["実装正本と技術標準資料。", "实现规范源与技术标准资料。", "Fuente canónica de implementación y materiales de estándares técnicos.", "Fonte canonica dell’implementazione e documenti degli standard tecnici.", "المصدر المعياري للتنفيذ ووثائق المعايير التقنية."],
  ["実装対話の精度を支える技術用語集", "支持准确实现沟通的技术术语表", "Glosario técnico para conversaciones de implementación precisas", "Glossario tecnico per confronti di implementazione accurati", "مسرد تقني يدعم دقة حوارات التنفيذ"],
  ["実値はAWS Runtime Acceptance完了後、承認済みNetwork Registryから公開します。未確定値は推測しません。", "实际值将在AWS Runtime Acceptance完成后从已批准的Network Registry发布。不推测未确定的值。", "Los valores reales se publicarán desde el Network Registry aprobado tras completar AWS Runtime Acceptance. No se estiman valores no confirmados.", "I valori reali saranno pubblicati dal Network Registry approvato dopo il completamento di AWS Runtime Acceptance. I valori non confermati non vengono stimati.", "تُنشر القيم الفعلية من سجل الشبكة المعتمد بعد اكتمال قبول وقت تشغيل AWS، ولا تُخمّن القيم غير المؤكدة."],
  ["受入判定", "验收判定", "Decisión de aceptación", "Decisione di accettazione", "قرار القبول"],
  ["重複・未知ValidatorをFail-Closedで拒否", "以失败关闭方式拒绝重复和未知验证者", "Rechazar de forma fail-closed validadores duplicados y desconocidos", "Rifiutare in modalità fail-closed validatori duplicati e sconosciuti", "رفض المدققين المكررين والمجهولين بأسلوب الإغلاق عند الفشل"],
  ["承認済みNetwork Registryのみを使用し、未確定値を推測しません。", "仅使用已批准的Network Registry，不推测未确定的值。", "Usar únicamente el Network Registry aprobado, sin estimar valores no confirmados.", "Usare solo il Network Registry approvato, senza stimare valori non confermati.", "استخدام سجل الشبكة المعتمد فقط وعدم تخمين القيم غير المؤكدة."],
  ["承認対象のトークン規格、アップグレード方式、開発ツールは、公開前にクライアント互換性、Negative Test、配置検証を完了します。", "待批准的代币标准、升级方式和开发工具必须在发布前完成客户端兼容性、负向测试和部署验证。", "Los estándares de tokens, métodos de actualización y herramientas de desarrollo sujetos a aprobación deben completar compatibilidad de clientes, pruebas negativas y verificación de despliegue antes de publicarse.", "Standard token, metodi di upgrade e strumenti di sviluppo soggetti ad approvazione devono completare compatibilità client, test negativi e verifica del deployment prima della pubblicazione.", "يجب أن تستكمل معايير الرموز وطرق الترقية وأدوات التطوير الخاضعة للموافقة توافق العميل والاختبارات السلبية والتحقق من النشر قبل نشرها."],
  ["証跡・受入判定", "证据与验收判定", "Evidencia y aceptación", "Evidenze e accettazione", "الأدلة وقرار القبول"],
  ["証跡マトリクス", "证据矩阵", "Matriz de evidencia", "Matrice delle evidenze", "مصفوفة الأدلة"],
  ["証跡分類", "证据分类", "Clasificación de evidencia", "Classificazione delle evidenze", "تصنيف الأدلة"],
  ["制度的ガバナンス", "机构治理", "Gobernanza institucional", "Governance istituzionale", "الحوكمة المؤسسية"],
  ["制度的ガバナンス・責任分界・セキュリティ", "机构治理、责任边界与安全", "Gobernanza institucional, responsabilidades y seguridad", "Governance istituzionale, responsabilità e sicurezza", "الحوكمة المؤسسية وحدود المسؤولية والأمن"],
  ["制度的実装のための共通言語。", "面向机构实现的共同语言。", "Lenguaje común para la implementación institucional.", "Linguaggio comune per l’implementazione istituzionale.", "لغة مشتركة للتنفيذ المؤسسي."],
  ["制度的統制", "机构控制", "Control institucional", "Controllo istituzionale", "الضبط المؤسسي"],
  ["正本・技術資料", "规范源与技术资料", "Fuentes canónicas y documentación técnica", "Fonti canoniche e documentazione tecnica", "المصادر المعيارية والوثائق التقنية"],
  ["正本・受入判定・証跡マトリクス", "规范源、验收判定与证据矩阵", "Fuentes canónicas, aceptación y matriz de evidencia", "Fonti canoniche, accettazione e matrice delle evidenze", "المصادر المعيارية وقرار القبول ومصفوفة الأدلة"],
  ["正本境界", "规范源边界", "Límite de la fuente canónica", "Confine della fonte canonica", "حدود المصدر المعياري"],
  ["責任主体・権限・証跡を分離し、監査可能にする。", "分离责任主体、权限和证据，使其可审计。", "Separar responsables, permisos y evidencia para permitir la auditoría.", "Separare responsabili, autorizzazioni ed evidenze per renderli verificabili.", "فصل الجهات المسؤولة والصلاحيات والأدلة بما يتيح التدقيق."],
  ["前提環境、公開状態、テスト専用アカウントを確認します。", "确认前提环境、公开状态和测试专用账户。", "Confirmar el entorno requerido, el estado de publicación y las cuentas exclusivas de prueba.", "Verificare l’ambiente richiesto, lo stato di pubblicazione e gli account dedicati ai test.", "تأكيد البيئة المطلوبة وحالة النشر والحسابات المخصصة للاختبار."],
  ["相互運用", "互操作性", "Interoperabilidad", "Interoperabilità", "التشغيل البيني"],
  ["相互運用は、決定論的なFail-Closed経路検証、双方向メッセージ状態機械、 対象チェーン実行コントラクトで構成します。各経路は、ネットワーク識別、Custody、 Relayer Quorum、Finality、Replay Protection、利用上限、緊急停止を明示的に結合します。",
    "互操作性由确定性的失败关闭路径验证、双向消息状态机和目标链执行合约构成。每条路径均明确绑定网络标识、托管、中继者法定人数、终局性、重放保护、使用限额和紧急停止。",
    "La interoperabilidad se compone de validación determinista y fail-closed de rutas, una máquina de estados de mensajes bidireccional y contratos de ejecución en la cadena de destino. Cada ruta vincula explícitamente identificación de red, custodia, quórum de relayers, finalidad, protección contra replay, límites de uso y parada de emergencia.",
    "L’interoperabilità comprende validazione deterministica e fail-closed delle rotte, una macchina a stati per messaggi bidirezionali e contratti di esecuzione sulla chain di destinazione. Ogni rotta vincola esplicitamente identità di rete, custody, quorum dei relayer, finalità, protezione dal replay, limiti d’uso e arresto di emergenza.",
    "يتكون التشغيل البيني من تحقق حتمي مغلق عند الفشل للمسارات، وآلة حالات للرسائل ثنائية الاتجاه، وعقود تنفيذ على السلسلة المستهدفة. ويربط كل مسار صراحةً تعريف الشبكة والحفظ ونصاب المرحّلين والنهائية وحماية إعادة التشغيل وحدود الاستخدام والإيقاف الطارئ."],
  ["相互運用実装正本", "互操作实现规范源", "Fuente canónica de implementación de interoperabilidad", "Fonte canonica dell’implementazione di interoperabilità", "المصدر المعياري لتنفيذ التشغيل البيني"],
  ["定義から運用へ進む証跡基準の導入工程。", "从定义迈向运营的证据标准采用流程。", "Proceso de adopción de criterios de evidencia desde la definición hasta la operación.", "Percorso di adozione dei criteri di evidenza dalla definizione alle operazioni.", "مسار اعتماد معايير الأدلة من التعريف إلى التشغيل."],
  ["定義済みのリリース条件を満たしたか判定するための記録済み証跡。", "用于判定是否满足已定义发布条件的记录证据。", "Evidencia registrada para determinar si se cumplen las condiciones de release definidas.", "Evidenze registrate per stabilire se le condizioni di rilascio definite sono soddisfatte.", "أدلة مسجلة لتحديد ما إذا كانت شروط الإصدار المحددة قد تحققت."],
  ["定義済み確認方針に基づき、取引を十分に不可逆と扱う時点。", "根据已定义确认策略将交易视为充分不可逆的时点。", "Punto en el que una transacción se trata como suficientemente irreversible según la política de confirmación definida.", "Punto in cui una transazione è considerata sufficientemente irreversibile secondo la policy di conferma definita.", "النقطة التي تُعامل فيها المعاملة على أنها غير قابلة للعكس بما يكفي وفق سياسة التأكيد المحددة."],
  ["適用構造・実装・導入工程", "应用结构、实现与采用流程", "Estructura aplicada, implementación y adopción", "Struttura applicativa, implementazione e adozione", "هيكل التطبيق والتنفيذ ومسار التبني"],
  ["統制された公開検証と証跡収集を目的とするMainnet以外の環境。", "用于受控公开验证和证据收集的非Mainnet环境。", "Entorno distinto de Mainnet destinado a validación pública controlada y recopilación de evidencia.", "Ambiente diverso da Mainnet destinato alla validazione pubblica controllata e alla raccolta di evidenze.", "بيئة غير Mainnet مخصصة للتحقق العام المضبوط وجمع الأدلة."],
  ["統制された設定・試験用の予約識別子。公開稼働ネットワークの証明ではない。", "用于受控配置和测试的保留标识符；并不证明网络已公开运行。", "Identificador reservado para configuración y pruebas controladas; no demuestra una red pública en funcionamiento.", "Identificatore riservato a configurazione e test controllati; non prova l’esistenza di una rete pubblica operativa.", "معرّف محجوز للإعداد والاختبار المضبوطين، ولا يثبت وجود شبكة عامة قيد التشغيل."],
  ["導入・実装", "采用与实现", "Adopción e implementación", "Adozione e implementazione", "التبني والتنفيذ"],
  ["導入準備判定", "采用准备判定", "Evaluación de preparación para adopción", "Valutazione della preparazione all’adozione", "تقييم الجاهزية للتبني"],
  ["認証済みFinalityとValidator Epoch保護", "经认证的终局性与验证者纪元保护", "Finalidad certificada y protección de épocas de validadores", "Finalità certificata e protezione delle epoche dei validatori", "النهائية المعتمدة وحماية حقب المدققين"],
  ["配置・運用仕様", "部署与运营规范", "Especificaciones de despliegue y operación", "Specifiche di deployment e operazione", "مواصفات النشر والتشغيل"],
  ["配置済みインフラが承認されたネットワーク・セキュリティ境界内で動作することの証跡ベース確認。", "基于证据确认已部署基础设施在批准的网络与安全边界内运行。", "Confirmación basada en evidencia de que la infraestructura desplegada opera dentro de los límites de red y seguridad aprobados.", "Conferma basata su evidenze che l’infrastruttura distribuita operi entro i confini di rete e sicurezza approvati.", "تأكيد قائم على الأدلة بأن البنية التحتية المنشورة تعمل ضمن حدود الشبكة والأمن المعتمدة."],
  ["必要証跡と承認が揃うまで進行を停止するFail-Closed型の判断点。", "在所需证据和批准齐备前停止推进的失败关闭型决策点。", "Punto de decisión fail-closed que detiene el avance hasta reunir evidencia y aprobaciones requeridas.", "Punto decisionale fail-closed che arresta l’avanzamento finché non sono disponibili evidenze e approvazioni richieste.", "نقطة قرار مغلقة عند الفشل توقف التقدم حتى تكتمل الأدلة والموافقات المطلوبة."],
  ["本ページはチェーンの設計、実装、制度的ガバナンス、セキュリティ、受入判定に必要な技術証跡のみを扱います。法人情報、企業沿革、報道掲載はEvidenceの対象外です。", "本页面仅涵盖链设计、实现、机构治理、安全和验收判定所需的技术证据。法人信息、企业历史和媒体报道不属于Evidence范围。", "Esta página trata únicamente evidencia técnica necesaria para diseño, implementación, gobernanza institucional, seguridad y aceptación de la cadena. La información corporativa, la historia empresarial y la cobertura de prensa quedan fuera de Evidence.", "Questa pagina tratta solo le evidenze tecniche necessarie a progettazione, implementazione, governance istituzionale, sicurezza e accettazione della chain. Informazioni societarie, storia aziendale e copertura stampa sono escluse da Evidence.", "تغطي هذه الصفحة الأدلة التقنية اللازمة لتصميم السلسلة وتنفيذها وحوكمتها المؤسسية وأمنها وقبولها فقط. ولا تشمل Evidence معلومات الشركة أو تاريخها أو التغطية الصحفية."],
  ["明示されたネットワーク間のメッセージ・資産移動を統制する経路。", "控制指定网络之间消息和资产移动的路径。", "Ruta que controla mensajes y movimientos de activos entre redes especificadas.", "Rotta che controlla messaggi e movimenti di asset tra reti specificate.", "مسار يضبط الرسائل وحركة الأصول بين الشبكات المحددة."],
  ["有効Validator Set Hashを検証", "验证有效验证者集合哈希", "Verificar el hash del conjunto validador activo", "Verificare l’hash del set di validatori attivo", "التحقق من تجزئة مجموعة المدققين النشطة"],
  ["用途、供給、配布、Vesting、会計・法務上の責任を先に確定します。", "先确定用途、供应、分配、归属以及会计和法律责任。", "Definir primero finalidad, suministro, distribución, vesting y responsabilidades contables y jurídicas.", "Definire prima finalità, supply, distribuzione, vesting e responsabilità contabili e legali.", "تحديد الغرض والإمداد والتوزيع والاستحقاق والمسؤوليات المحاسبية والقانونية أولًا."],
];

export function secondaryTranslationIndex() {
  return new Map(
    secondaryTranslations.map(([ja, zh, es, it, ar], index) => [
      ja,
      {
        key: `secondary-${String(index + 1).padStart(3, "0")}`,
        values: { ja, zh, es, it, ar },
      },
    ]),
  );
}

export function renderSecondaryLanguageRuntime() {
  const entries = Object.fromEntries(
    [...secondaryTranslationIndex().values()].map(({ key, values }) => [key, values]),
  );
  return `(() => {
  "use strict";
  const storageKey = "junca-docs-secondary-language";
  const languages = ${JSON.stringify(secondaryLanguageMeta)};
  const copy = ${JSON.stringify(entries)};
  const select = document.getElementById("secondary-language-select");
  if (!(select instanceof HTMLSelectElement)) return;

  const supported = (value) => Object.prototype.hasOwnProperty.call(languages, value);
  const apply = (language) => {
    const selected = supported(language) ? language : "ja";
    const meta = languages[selected];
    document.querySelectorAll("[data-secondary-copy][data-secondary-key]").forEach((element) => {
      const record = copy[element.dataset.secondaryKey];
      if (!record || typeof record[selected] !== "string") return;
      element.textContent = record[selected];
      element.lang = meta.html;
      if (meta.dir === "rtl") element.dir = "rtl";
      else element.removeAttribute("dir");
    });
    select.value = selected;
    try { window.localStorage.setItem(storageKey, selected); } catch {}
  };

  let initial = "ja";
  try {
    const stored = window.localStorage.getItem(storageKey);
    if (stored && supported(stored)) initial = stored;
  } catch {}
  select.addEventListener("change", () => apply(select.value));
  window.addEventListener("pageshow", () => apply(select.value));
  apply(initial);
})();`;
}
