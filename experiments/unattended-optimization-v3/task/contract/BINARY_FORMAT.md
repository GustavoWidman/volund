# Fixture format v1

All fields are little-endian. Input file: ASCII magic `RQENG001` (8 bytes), uint64 event_count, uint64 query_count, event_count packed records `<QI i` (timestamp u64, stream u32, value i32; 16 bytes), then query_count packed records `<QQII` (lo u64, hi u64, stream u32, reserved u32; 24 bytes). No trailing bytes.

Expected-output file: ASCII magic `RQOUT001` (8 bytes), uint64 query_count, then packed `<Qqii` results (count u64, sum i64, minimum i32, maximum i32; 24 bytes). No trailing bytes. Empty match results are all zero. This on-disk representation is also the specified struct layout on the x86-64 Linux test host.
