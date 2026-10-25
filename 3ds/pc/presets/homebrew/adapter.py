from homebrew_runtime import HomebrewAdapter


def create_adapter(local_dir, manifest):
    return HomebrewAdapter(local_dir, manifest)
