# SPDX-License-Identifier: AGPL-3.0-or-later
from runtime import prepare_environment
prepare_environment()
from vendor_isolation import validate_isolation
validate_isolation()
from batch_translate import install
install()
from pdf2zh_next.main import cli
if __name__ == '__main__':
    cli()
