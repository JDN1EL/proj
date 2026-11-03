#!/usr/bin/env python3
# Leitor/extrator STFS (Xbox 360 CON) em modo somente leitura.
# Não modifica, reempacota nem assina o arquivo original.
from __future__ import annotations
import argparse
import hashlib
import json
import os
import struct
from pathlib import Path

BLOCK_SIZE = 0x1000
HASH_ENTRY_SIZE = 0x18
BLOCKS_PER_LEVEL = (170, 28900, 4913000)
END_OF_CHAIN = 0xFFFFFF

class STFSFormatError(Exception):
    pass

class STFSReader:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        if len(self.data) < 0x400 or self.data[:4] not in (b'CON ', b'LIVE', b'PIRS'):
            raise STFSFormatError('Assinatura/magic não reconhecida como pacote Xbox 360 STFS.')
        self.magic = self.data[:4].decode('ascii', 'replace').strip()
        self.header_size = self._u32be(0x340)
        if not self.header_size or self.header_size > len(self.data):
            raise STFSFormatError(f'Tamanho de cabeçalho inválido: 0x{self.header_size:X}.')
        self.content_type = self._u32be(0x344)
        self.metadata_version = self._u32be(0x348)
        self.content_size = self._u64be(0x34C)
        self.media_id = self._u32be(0x354)
        self.title_id = self._u32be(0x360)
        self.title_name = self._utf16be(0x1691, 0x80)
        self.display_names = [self._utf16be(0x411 + i * 0x100, 0x100) for i in range(9)]
        self.volume_type = self._u32be(0x3A9)
        if self.volume_type != 0:
            raise STFSFormatError('O pacote é SVOD, não STFS; este leitor cobre somente STFS.')
        d = 0x379
        if self.data[d] != 0x24:
            raise STFSFormatError('Descritor de volume STFS inválido.')
        self.flags = self.data[d + 2]
        self.read_only_format = bool(self.flags & 1)
        self.root_active_index = bool(self.flags & 2)
        self.file_table_block_count = struct.unpack_from('<H', self.data, d + 3)[0]
        self.file_table_start_block = int.from_bytes(self.data[d + 5:d + 8], 'little')
        self.top_hash = self.data[d + 8:d + 28]
        self.total_blocks = self._u32be(d + 0x1C)
        self.free_blocks = self._u32be(d + 0x20)
        self.blocks_per_hash_table = 1 if self.read_only_format else 2
        self.data_base = (self.header_size + BLOCK_SIZE - 1) & ~(BLOCK_SIZE - 1)
        self._validate_header()

    def _u32be(self, off): return struct.unpack_from('>I', self.data, off)[0]
    def _u64be(self, off): return struct.unpack_from('>Q', self.data, off)[0]
    def _utf16be(self, off, size): return self.data[off:off + size].decode('utf-16-be', errors='ignore').split('\x00', 1)[0]

    def _validate_header(self):
        if self.file_table_block_count < 1 or self.total_blocks < 1:
            raise STFSFormatError('Contagem de blocos inválida no descritor STFS.')
        if self.data_base >= len(self.data):
            raise STFSFormatError('Cabeçalho STFS ocupa o arquivo inteiro.')
        if self.total_blocks > 0x100000:
            raise STFSFormatError('Contagem de blocos excede o limite defensivo do leitor.')

    def block_to_offset(self, block_index: int) -> int:
        if block_index < 0 or block_index >= self.total_blocks:
            raise STFSFormatError(f'Índice de bloco inválido: {block_index}.')
        block = block_index
        base = BLOCKS_PER_LEVEL[0]
        for _ in range(3):
            block += ((block_index + base) // base) * self.blocks_per_hash_table
            if block_index < base:
                break
            base *= BLOCKS_PER_LEVEL[0]
        off = self.data_base + (block << 12)
        if off + BLOCK_SIZE > len(self.data):
            raise STFSFormatError(f'Bloco {block_index} aponta para fora do pacote (0x{off:X}).')
        return off

    def hash_table_block_number(self, block_index: int, level: int) -> int:
        bpht = self.blocks_per_hash_table
        step0 = BLOCKS_PER_LEVEL[0] + bpht
        step1 = BLOCKS_PER_LEVEL[1] + ((BLOCKS_PER_LEVEL[0] + 1) * bpht)
        if level == 0:
            if block_index < BLOCKS_PER_LEVEL[0]:
                return 0
            block = (block_index // BLOCKS_PER_LEVEL[0]) * step0
            block += ((block_index // BLOCKS_PER_LEVEL[1]) + 1) * bpht
            return block if block_index < BLOCKS_PER_LEVEL[1] else block + bpht
        if level == 1:
            if block_index < BLOCKS_PER_LEVEL[1]:
                return step0
            return (block_index // BLOCKS_PER_LEVEL[1]) * step1 + bpht
        return step1

    def hash_table_offset(self, block_index: int, level: int) -> int:
        return self.data_base + (self.hash_table_block_number(block_index, level) << 12)

    def _hash_entry(self, block_index: int):
        secondary = BLOCK_SIZE if self.root_active_index else 0
        if not self.read_only_format and self.total_blocks > BLOCKS_PER_LEVEL[0]:
            if self.total_blocks > BLOCKS_PER_LEVEL[1]:
                off2 = self.hash_table_offset(block_index, 2) + secondary
                ent2 = off2 + (((block_index // BLOCKS_PER_LEVEL[1]) % 170) * HASH_ENTRY_SIZE)
                info2 = int.from_bytes(self.data[ent2 + 20:ent2 + 24], 'big')
                secondary = BLOCK_SIZE if (info2 & 0x40000000) else 0
            off1 = self.hash_table_offset(block_index, 1) + secondary
            ent1 = off1 + (((block_index // BLOCKS_PER_LEVEL[0]) % 170) * HASH_ENTRY_SIZE)
            info1 = int.from_bytes(self.data[ent1 + 20:ent1 + 24], 'big')
            secondary = BLOCK_SIZE if (info1 & 0x40000000) else 0
        off0 = self.hash_table_offset(block_index, 0) + secondary
        entry_off = off0 + ((block_index % BLOCKS_PER_LEVEL[0]) * HASH_ENTRY_SIZE)
        entry = self.data[entry_off:entry_off + HASH_ENTRY_SIZE]
        if len(entry) != HASH_ENTRY_SIZE:
            raise STFSFormatError(f'Tabela de hash incompleta para o bloco {block_index}.')
        info = int.from_bytes(entry[20:24], 'big')
        return entry[:20], info & 0xFFFFFF

    def read_block(self, block_index: int, verify_hash=True) -> bytes:
        off = self.block_to_offset(block_index)
        block = self.data[off:off + BLOCK_SIZE]
        if verify_hash:
            expected, _ = self._hash_entry(block_index)
            actual = hashlib.sha1(block).digest()
            if actual != expected:
                raise STFSFormatError(f'Hash SHA-1 inválido no bloco {block_index} (0x{off:X}).')
        return block

    def read_chain(self, start_block: int, length: int, allocated_blocks: int | None = None,
                   verify_hash=True):
        if length < 0 or length > len(self.data) * 64:
            raise STFSFormatError('Comprimento de arquivo inválido.')
        out = bytearray()
        chain = []
        current = start_block
        while len(out) < length:
            if current == END_OF_CHAIN:
                raise STFSFormatError(f'Cadeia terminou antes do esperado ({len(out)}/{length} bytes).')
            if current in chain:
                raise STFSFormatError(f'Ciclo detectado na cadeia de blocos no bloco {current}.')
            if len(chain) >= self.total_blocks:
                raise STFSFormatError('Cadeia ultrapassa o total de blocos do pacote.')
            block = self.read_block(current, verify_hash=verify_hash)
            take = min(BLOCK_SIZE, length - len(out))
            out.extend(block[:take])
            chain.append(current)
            _, current = self._hash_entry(current)
        if allocated_blocks is not None and len(chain) != allocated_blocks:
            raise STFSFormatError(f'Cadeia tem {len(chain)} blocos, descritor informa {allocated_blocks}.')
        return bytes(out), chain

    def list_entries(self, verify_hash=True):
        table, table_chain = self.read_chain(self.file_table_start_block,
                                             self.file_table_block_count * BLOCK_SIZE,
                                             self.file_table_block_count, verify_hash)
        entries = []
        for block_no in range(self.file_table_block_count):
            chunk = table[block_no * BLOCK_SIZE:(block_no + 1) * BLOCK_SIZE]
            for idx in range(BLOCK_SIZE // 0x40):
                e = chunk[idx * 0x40:(idx + 1) * 0x40]
                if not e or e[0] == 0:
                    break
                name_len = e[40] & 0x3F
                name = e[:name_len].decode('ascii', 'replace')
                is_dir = bool(e[40] & 0x80)
                valid = int.from_bytes(e[41:44], 'little')
                allocated = int.from_bytes(e[44:47], 'little')
                start = int.from_bytes(e[47:50], 'little')
                parent = int.from_bytes(e[50:52], 'big')
                length = int.from_bytes(e[52:56], 'big')
                entries.append({'index':len(entries),'name':name,'is_dir':is_dir,
                                'valid_blocks':valid,'allocated_blocks':allocated,
                                'start_block':start,'parent_index':parent,'size':length})
        return entries, table_chain

    def extract_all(self, output_dir: str | Path, verify_hash=True):
        out_root = Path(output_dir)
        out_root.mkdir(parents=True, exist_ok=True)
        entries, _ = self.list_entries(verify_hash=verify_hash)
        made = []
        paths = {}
        for entry in entries:
            name = entry['name']
            # Refuse path traversal or unsafe names.
            if name in ('', '.', '..') or '/' in name or '\\' in name or ':' in name:
                raise STFSFormatError(f'Nome de arquivo inseguro no pacote: {name!r}.')
            parent = entry['parent_index']
            parent_path = out_root if parent == 0xFFFF else paths.get(parent)
            if parent_path is None:
                raise STFSFormatError(f'Diretório pai inválido no item {name!r}.')
            target = parent_path / name
            if entry['is_dir']:
                target.mkdir(parents=True, exist_ok=True)
            else:
                content, chain = self.read_chain(entry['start_block'], entry['size'],
                                                 entry['allocated_blocks'], verify_hash)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                made.append({'name':name,'size':len(content),'blocks':len(chain),
                             'sha256':hashlib.sha256(content).hexdigest(),
                             'path':str(target)})
            paths[entry['index']] = target
        return made

    def report(self, verify_all=True):
        entries, table_chain = self.list_entries(verify_hash=True)
        report = {
            'file':self.path.name,'package_magic':self.magic,
            'file_size':len(self.data),'header_size':self.header_size,
            'content_type':self.content_type,'content_type_label':
                ('Saved Game' if self.content_type==1 else f'0x{self.content_type:X}'),
            'metadata_version':self.metadata_version,'media_id':f'0x{self.media_id:08X}',
            'title_id':f'0x{self.title_id:08X}','title_name':self.title_name,
            'display_names':self.display_names,
            'volume_type':self.volume_type,'volume_flags':self.flags,
            'read_only_format':self.read_only_format,
            'root_active_index':self.root_active_index,
            'file_table_block_count':self.file_table_block_count,
            'file_table_start_block':self.file_table_start_block,
            'total_blocks':self.total_blocks,'free_blocks':self.free_blocks,
            'table_chain':table_chain,'entries':entries,
        }
        if verify_all:
            checked=set(table_chain)
            for e in entries:
                if not e['is_dir']:
                    _, chain=self.read_chain(e['start_block'],e['size'],e['allocated_blocks'],True)
                    checked.update(chain)
            report['data_blocks_sha1_verified']=len(checked)
            report['sha1_verification']='OK'
        return report

def main():
    ap=argparse.ArgumentParser(description='Inspeciona/extrai pacotes Xbox 360 STFS sem modificar o original.')
    ap.add_argument('package',help='Arquivo EDIT/CON/LIVE/PIRS')
    ap.add_argument('--list',action='store_true',help='Lista conteúdo sem extrair')
    ap.add_argument('--extract',metavar='PASTA',help='Extrai os arquivos para a pasta indicada')
    ap.add_argument('--report',metavar='JSON',help='Salva relatório JSON')
    ap.add_argument('--no-verify',action='store_true',help='Desativa checagem SHA-1 (não recomendado)')
    args=ap.parse_args()
    reader=STFSReader(args.package)
    if args.list or (not args.extract and not args.report):
        entries,_=reader.list_entries(verify_hash=not args.no_verify)
        print(f'{reader.magic} | {len(reader.data)} bytes | content type={reader.content_type} | blocos={reader.total_blocks}')
        for e in entries: print(f"{'DIR ' if e['is_dir'] else 'FILE'} {e['name']} | {e['size']} bytes | bloco {e['start_block']} | {e['allocated_blocks']} blocos")
    if args.extract:
        for e in reader.extract_all(args.extract,verify_hash=not args.no_verify):
            print(f"Extraído: {e['name']} ({e['size']} bytes) SHA256={e['sha256']}")
    if args.report:
        report=reader.report(verify_all=not args.no_verify)
        Path(args.report).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print('Relatório:',args.report)

if __name__=='__main__':
    try: main()
    except (OSError,STFSFormatError,struct.error) as exc:
        raise SystemExit(f'Erro: {exc}')
