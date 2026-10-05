# hook-tkinterdnd2.py
# PyInstaller フック: tkinterdnd2 の tkdnd DLL をバンドルに含める

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# tkdnd バイナリ (.dll) を収集
binaries = collect_dynamic_libs('tkinterdnd2')

# テーマやデータファイルも収集
datas = collect_data_files('tkinterdnd2')
