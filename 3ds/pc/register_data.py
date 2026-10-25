"""Register owned game assets locally; paths and game files never enter Git."""
import argparse
import json
from pathlib import Path
from homebrew_data import register

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--target', required=True, help='SD game-data root, for example doom3/base')
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    print(json.dumps(register(args.folder, args.target, args.name,
                             Path(__file__).resolve().parent / 'local/homebrew/data-packages'), indent=2))
