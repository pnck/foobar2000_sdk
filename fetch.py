import requests
from lxml import html
import git
import logging
from contextlib import contextmanager
import os
import sys
import shutil

logging.basicConfig(level=logging.DEBUG)


def fetch_sdk_version():
    url = "https://www.foobar2000.org/SDK"
    response = requests.get(url)
    response.raise_for_status()  # Raise an error for HTTP issues
    tree = html.fromstring(response.content)

    version_element = tree.xpath("//a[contains(@href, '/getfile/')]")
    if version_element:
        return version_element
    else:
        raise ValueError("Could not find the newest SDK version on the page.")


def fetch_repo():
    repo = git.Repo(".")
    repo.git.fetch("--tags")
    logging.debug(f"Fetched tags: {[t.name for t in repo.tags]}")
    logging.debug(f"Branches: {[b.name for b in repo.branches]}")
    logging.debug(f"Remote Refs: {[b.name for b in repo.remote().refs]}")
    return repo


@contextmanager
def create_tagged_version_safe(repo, tag_name, ver_link):
    cur_branch = repo.active_branch
    archive_name = "foobar2000-sdk.7z"
    try:
        # create a new branch from the main branch
        new_branch = repo.create_head(tag_name, "origin/main")
        new_branch.checkout()

        # download the SDK version and save it to the repo
        with open(archive_name, "wb") as f:
            response = requests.get(ver_link, stream=True)
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # extract the archive with 7z command
        _7z = shutil.which("7z")
        if _7z is None:
            _7z = shutil.which("7zz")
        if _7z is None:
            raise FileNotFoundError("7z or 7zz command not found.")
        os.system(f"{_7z} x {archive_name} -y")
        # remove the archive
        os.remove(archive_name)
        # add the files to the repo
        repo.git.add(".")
        # commit the changes
        repo.git.commit(m=f"add: auto fetch {tag_name} SDK version")
        # tag the commit
        repo.git.tag(tag_name)

        yield new_branch
    except Exception as e:
        if repo.active_branch.name != cur_branch.name:
            repo.git.reset("--hard")
            # repo.git.clean("-fd")
            cur_branch.checkout()
            try:
                repo.delete_head(new_branch, force=True)
            finally:
                pass
        raise e
    finally:
        cur_branch.checkout()
        # cleanup
        if os.path.exists(archive_name):
            os.remove(archive_name)


def create_tagged_version(repo, tag_name, ver_link):
    with create_tagged_version_safe(repo, tag_name, ver_link) as ver:
        ver.checkout()
        logging.info(f"Successfully created version {ver.name}.")
    # delete the branch after use by name
    repo.delete_head(tag_name, force=True)


def update_date(repo):
    cur_branch = repo.active_branch
    from datetime import datetime

    date = datetime.now().strftime(r"%Y%m%d")
    try:
        repo.branches["fetch"].checkout()
        r = repo.remote("origin").pull("fetch")[0]
        if r.flags == 0:
            with open("README.md", "r+") as f:
                lines = f.readlines()
                for l in lines:
                    if l.startswith("> Last run:"):
                        lines[lines.index(l)] = f"> Last run: {date}\n"
                f.seek(0)
                f.truncate(0)
                f.writelines(lines)
            updated_files = ["README.md"]
            repo.index.add(updated_files)
            repo.index.commit(f"update at {date}")
    finally:
        cur_branch.checkout()


if __name__ == "__main__":

    try:
        elements = fetch_sdk_version()
        links = {
            x.text.strip(): f"https://www.foobar2000.org{x.attrib['href'].replace('getfile','files')}"
            for x in elements
            if "SDK " in x.text
        }
        logging.debug(f"Found foobar2000 SDK versions: {[k for k in links.keys()]}")
        repo = fetch_repo()
        repo_tags = {t.name: t for t in repo.tags}
        for k in links.keys():
            tag_name = k.split(" ")[1]
            if tag_name in repo_tags:
                logging.debug(f"Tag {tag_name} already exists.")
            else:
                logging.debug(f"Creating new tag {tag_name}.")
                create_tagged_version(repo, tag_name, links[k])
        if len(sys.argv) > 1 and sys.argv[1] == "push":
            logging.info("Pushing changes to remote.")
            repo.git.push("origin", "--tags")
            update_date(repo)
            repo.git.push("origin", "fetch")
    except Exception as e:
        logging.error(f"Error: {e}")
        exit(1)
