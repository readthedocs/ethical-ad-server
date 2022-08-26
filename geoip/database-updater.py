import argparse
import io
import os
import shutil
import tarfile
import zipfile

import requests


# Used for GeoIP databases
MAXMIND_LICENSE_KEY = os.environ.get("MAXMIND_LICENSE_KEY")

# Available from https://www.maxmind.com/en/accounts/759054/geoip/downloads
#  under "Get Permalinks"
MAXMIND_COUNTRY_DATABASE = f"https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-Country&license_key={MAXMIND_LICENSE_KEY}&suffix=tar.gz"
MAXMIND_CITY_DATABASE = f"https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key={MAXMIND_LICENSE_KEY}&suffix=tar.gz"

# Used for the IP2Location IP2Proxy database
IP2LOCATION_TOKEN = os.environ.get("IP2LOCATION_TOKEN")

# Results in a zipfile
IP2LOCATION_IPPROXY = (
    f"https://www.ip2location.com/download?token={IP2LOCATION_TOKEN}&file=PX2BIN"
)
# Our filename under geoip/
IPPROXY_FILENAME = "IP2Proxy.BIN"

# List of tor exit nodes which changes periodically
# Maintained by the Tor project
TOR_EXIT_NODES_URL = "https://check.torproject.org/torbulkexitlist"
TOR_EXIT_NODES_FILENAME = "torbulkexitlist.txt"


def update_maxmind_dbs(outdir):
    print("Updating the GeoIP databases from MaxMind...")

    if not MAXMIND_LICENSE_KEY:
        raise RuntimeError(
            "No envvar MAXMIND_LICENSE_KEY. "
            "Cannot download the databases without this. "
            "Create a MaxMind account."
        )

    for url in (MAXMIND_COUNTRY_DATABASE, MAXMIND_CITY_DATABASE):
        resp = requests.get(url)
        if not resp.ok:
            raise RuntimeError(
                f"Failed to update GeoIP database: {url}. Status_code={resp.status_code}"
            )

        with tarfile.open(mode="r:gz", fileobj=io.BytesIO(resp.content)) as tar:
            for member in tar.getmembers():
                if member.name.endswith(".mmdb"):
                    filename = member.name[member.name.rfind("/") + 1 :]
                    outpath = os.path.join(outdir, filename)
                    print(f"Writing database to {outpath}...")
                    buf = tar.extractfile(member)
                    with open(outpath, "wb") as fd:
                        fd.write(buf.read())
                    break
            else:
                # Only taken if there was no "break" executed
                raise RuntimeError("No .mmdb file found in the download")


def update_ipproxy_db(outdir):
    print("Updating the IPProxy database...")

    if not IP2LOCATION_TOKEN:
        raise RuntimeError(
            "No envvar IP2LOCATION_TOKEN. "
            "Cannot download the IP2Proxy database without this. "
            "This is a commercial product and must be purchased at ip2location.com."
        )

    url = IP2LOCATION_IPPROXY
    resp = requests.get(url)
    if not resp.ok:
        raise RuntimeError(
            f"Failed to update IP2Proxy database: {url}. Status_code={resp.status_code}"
        )

    with zipfile.ZipFile(io.BytesIO(resp.content), mode="r") as myzip:
        for member in myzip.infolist():
            if member.filename.lower().endswith(".bin"):
                outpath = os.path.join(outdir, IPPROXY_FILENAME)
                print(f"Writing database to {outpath}...")
                myzip.extract(member, path=outdir)
                shutil.copyfile(os.path.join(outdir, member.filename), outpath)
                break
        else:
            # Only taken if there was no "break" executed
            raise RuntimeError("No .mmdb file found in the download")


def update_torexit_list(outdir):
    print("Updating Tor exit nodes list...")

    url = TOR_EXIT_NODES_URL
    resp = requests.get(url)
    if not resp.ok:
        raise RuntimeError(
            f"Failed to update Tor exit nodes list: {url}. Status_code={resp.status_code}"
        )

    outpath = os.path.join(outdir, TOR_EXIT_NODES_FILENAME)
    print(f"Writing Tor exit nodes list to {outpath}...")
    with open(outpath, "wb") as fd:
        fd.write(resp.content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download and update GeoIP and IPProxy databases."
    )
    parser.add_argument(
        "--geoip-only",
        action="store_true",
        help="Only download the GeoIP databases, not the IPProxy DB.",
    )
    parser.add_argument(
        "--ipproxy-only",
        action="store_true",
        help="Only download the IPProxy DB, not the GeoIP databases.",
    )
    parser.add_argument(
        "--outdir",
        default=os.getcwd(),
        help="Directory to output the updated databases.",
    )

    args = parser.parse_args()

    if not args.geoip_only:
        update_torexit_list(args.outdir)
        update_ipproxy_db(args.outdir)
    if not args.ipproxy_only:
        update_maxmind_dbs(args.outdir)
