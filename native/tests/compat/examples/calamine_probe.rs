use calamine::{open_workbook, Reader, Xlsx};
fn main() {
    let path = std::env::temp_dir().join("probe_debug.xlsx");
    let mut wb: Xlsx<_> = open_workbook(&path).unwrap();
    let range = wb.worksheet_range("Item").unwrap();
    println!("range start: {:?}", range.start());
    for (r, c, v) in range.cells() {
        println!("cells(): r={r} c={c} v={v:?}");
    }
}
