//! 工作簿读取（任务 1.5 原型）：对照 openpyxl（read_only+data_only）语义。
//!
//! 行为边界与选型结论见 `native/docs/excel-reading-findings.md`。

use std::fmt;
use std::io::Read;
use std::path::Path;

use calamine::{open_workbook, CellErrorType, Data, Reader, Xlsx};

/// 单元格语义分类，与 `fixtures/excel/expected/*.json` 的 `kind` 对齐。
#[derive(Debug, Clone, PartialEq)]
pub enum ProbeValue {
    Text(String),
    /// 数值统一按 f64 承载（openpyxl 的 int/float 之分不跨语言稳定）。
    Number(f64),
    Bool(bool),
    /// ISO 8601 秒精度字符串，与 openpyxl `isoformat()` 对齐。
    DateTime(String),
    /// Excel 错误码文本（如 `#DIV/0!`）。
    Error(String),
}

/// 1-based 坐标（与 Excel UI / excelRow 诊断一致）。
#[derive(Debug, Clone, PartialEq)]
pub struct ProbeCell {
    pub row: u32,
    pub col: u32,
    pub value: ProbeValue,
}

/// 工作簿读取探针报告。
#[derive(Debug, Clone, PartialEq)]
pub struct ProbeReport {
    pub sheets: Vec<String>,
    /// 活跃 Sheet（workbookView activeTab）；calamine 不暴露，自 workbook.xml 读取。
    pub active_sheet: Option<String>,
    /// workbookPr date1904；calamine 不暴露工作区级访问，自 workbook.xml 读取。
    pub is_1904: bool,
    /// 活跃 Sheet 的非空单元格（calamine 的 used range 语义）。
    pub cells: Vec<ProbeCell>,
}

/// 探针错误。
#[derive(Debug)]
pub enum ProbeError {
    Io(std::io::Error),
    Calamine(calamine::XlsxError),
    Zip(zip::result::ZipError),
    /// workbook.xml 不是合法 UTF-8。
    WorkbookXmlEncoding,
}

impl fmt::Display for ProbeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ProbeError::Io(e) => write!(f, "读取文件失败: {e}"),
            ProbeError::Calamine(e) => write!(f, "解析工作簿失败: {e}"),
            ProbeError::Zip(e) => write!(f, "解包 xlsx 失败: {e}"),
            ProbeError::WorkbookXmlEncoding => write!(f, "workbook.xml 不是合法 UTF-8"),
        }
    }
}

impl std::error::Error for ProbeError {}

impl From<std::io::Error> for ProbeError {
    fn from(e: std::io::Error) -> Self {
        ProbeError::Io(e)
    }
}
impl From<calamine::XlsxError> for ProbeError {
    fn from(e: calamine::XlsxError) -> Self {
        ProbeError::Calamine(e)
    }
}
impl From<zip::result::ZipError> for ProbeError {
    fn from(e: zip::result::ZipError) -> Self {
        ProbeError::Zip(e)
    }
}

fn error_text(e: &CellErrorType) -> String {
    match e {
        CellErrorType::Div0 => "#DIV/0!",
        CellErrorType::NA => "#N/A",
        CellErrorType::Name => "#NAME?",
        CellErrorType::Null => "#NULL!",
        CellErrorType::Num => "#NUM!",
        CellErrorType::Ref => "#REF!",
        CellErrorType::Value => "#VALUE!",
        CellErrorType::GettingData => "#GETTING_DATA",
    }
    // calamine 0.36 的 CellErrorType 恰好是这 8 个变体；上游新增变体时
    // 此处会编译失败，届时显式决定映射，而不是静默兜底。
    .to_string()
}

/// 从 xl/workbook.xml 提取 activeTab / date1904（calamine 不暴露的缺口）。
///
/// 原型级实现：属性字符串扫描。正式实现若换用 XML 解析器，行为必须保持。
fn workbook_view_flags(path: &Path) -> Result<(Option<usize>, bool), ProbeError> {
    let file = std::fs::File::open(path)?;
    workbook_view_flags_from(zip::ZipArchive::new(file)?)
}

fn workbook_view_flags_from_bytes(bytes: &[u8]) -> Result<(Option<usize>, bool), ProbeError> {
    workbook_view_flags_from(zip::ZipArchive::new(std::io::Cursor::new(bytes))?)
}

fn workbook_view_flags_from<R: std::io::Read + std::io::Seek>(
    mut archive: zip::ZipArchive<R>,
) -> Result<(Option<usize>, bool), ProbeError> {
    let mut entry = archive.by_name("xl/workbook.xml")?;
    let mut text = String::new();
    entry
        .read_to_string(&mut text)
        .map_err(|_| ProbeError::WorkbookXmlEncoding)?;

    let active_tab = text
        .split("activeTab=\"")
        .nth(1)
        .and_then(|rest| rest.split('"').next())
        .and_then(|digits| digits.parse::<usize>().ok());
    let date1904 = text.contains("date1904=\"1\"")
        || text.contains("date1904=\"true\"")
        || text.contains("date1904=\"True\"");
    Ok((active_tab, date1904))
}

/// Howard Hinnant 的 civil_from_days：自 1970-01-01 的天数 → (年, 月, 日)。
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let mut y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    if m <= 2 {
        y += 1;
    }
    (y, m, d)
}

/// Excel serial → ISO 8601（秒精度）。1900 系以 1899-12-30 为基（含闰年 bug 兼容），
/// 1904 系以 1904-01-01 为基。
pub fn serial_to_iso(serial: f64, is_1904: bool) -> String {
    let unix_base: f64 = if is_1904 { -24_107.0 } else { -25_569.0 };
    let days = (serial + unix_base).floor() as i64;
    let frac = serial + unix_base - days as f64;
    let secs = (frac * 86_400.0).round() as u32;
    let (y, m, d) = civil_from_days(days);
    format!(
        "{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}",
        secs / 3600,
        (secs % 3600) / 60,
        secs % 60
    )
}

fn probe_value(data: &Data, is_1904: bool) -> Option<ProbeValue> {
    match data {
        Data::Empty => None,
        Data::Int(v) => Some(ProbeValue::Number(*v as f64)),
        Data::Float(v) => Some(ProbeValue::Number(*v)),
        Data::String(s) => Some(ProbeValue::Text(s.to_string())),
        Data::Bool(b) => Some(ProbeValue::Bool(*b)),
        Data::DateTime(dt) => Some(ProbeValue::DateTime(serial_to_iso(dt.as_f64(), is_1904))),
        // openpyxl 对 ISO 日期串按文本返回；保持一致（夹具未覆盖，见 findings）。
        Data::DateTimeIso(s) => Some(ProbeValue::Text(s.to_string())),
        Data::DurationIso(s) => Some(ProbeValue::Text(s.to_string())),
        Data::Error(e) => Some(ProbeValue::Error(error_text(e))),
    }
}

/// 读取工作簿并产出探针报告（活跃 Sheet 的非空单元格）。
pub fn probe_xlsx(path: &Path) -> Result<ProbeReport, ProbeError> {
    let (active_tab, is_1904) = workbook_view_flags(path)?;
    let workbook: Xlsx<_> = open_workbook(path)?;
    probe_from_workbook(workbook, active_tab, is_1904)
}

/// 从捕获字节产出探针报告（导出期：解析用的字节与复核的字节是同一份）。
pub fn probe_xlsx_bytes(bytes: &[u8]) -> Result<ProbeReport, ProbeError> {
    let (active_tab, is_1904) = workbook_view_flags_from_bytes(bytes)?;
    let workbook: Xlsx<_> = calamine::open_workbook_from_rs(std::io::Cursor::new(bytes))?;
    probe_from_workbook(workbook, active_tab, is_1904)
}

fn probe_from_workbook<R: std::io::Read + std::io::Seek>(
    mut workbook: Xlsx<R>,
    active_tab: Option<usize>,
    is_1904: bool,
) -> Result<ProbeReport, ProbeError> {
    let sheets = workbook.sheet_names().to_vec();
    let active_sheet = active_tab
        .and_then(|idx| sheets.get(idx).cloned())
        .or_else(|| sheets.first().cloned());

    let mut cells = Vec::new();
    if let Some(name) = &active_sheet {
        let range = workbook.worksheet_range(name)?;
        // calamine 的 cells() 坐标是 range 内的相对坐标；全空的前导行/列会让
        // range 起点偏移，必须加回 start 才是绝对坐标。
        let (start_row, start_col) = range.start().unwrap_or((0, 0));
        for (row, col, data) in range.cells() {
            if let Some(value) = probe_value(data, is_1904) {
                cells.push(ProbeCell {
                    row: (start_row as usize + row + 1) as u32,
                    col: (start_col as usize + col + 1) as u32,
                    value,
                });
            }
        }
    }

    Ok(ProbeReport {
        sheets,
        active_sheet,
        is_1904,
        cells,
    })
}
