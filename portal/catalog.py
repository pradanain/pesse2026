"""Explicit source grain; ART and business indexes are independent namespaces."""
SOURCES = {
    'VALIDASI_KODE_SLS.xlsx': ('regions', 'region'),
    'master_assignment.xlsx': ('master', 'assignment'),
    'identitas_keluarga.xlsx': ('family', 'assignment'),
    'roster_anggota_keluarga.xlsx': ('members', 'member'),
    'SCREENING_USAHA_KELUARGA.xlsx': ('screening', 'assignment'),
    'IDENTITAS_USAHA_ROSTER.xlsx': ('businesses', 'business'),
    'KEGIATAN_KBLI_USAHA.xlsx': ('activities', 'business'),
    'TENAGA_KERJA_KEUANGAN_USAHA.xlsx': ('business_finance', 'business'),
    'PENDIDIKAN_PEKERJAAN_ART.xlsx': ('education', 'member'),
    'PENDAPATAN_PER_ART.xlsx': ('income', 'member'),
    'RUMAH_SANITASI_FASILITAS.xlsx': ('housing', 'assignment'),
    'PENDAPATAN_PENGELUARAN_KELUARGA.xlsx': ('economy', 'assignment'),
    'ASET_KELUARGA.xlsx': ('assets', 'assignment'),
}
