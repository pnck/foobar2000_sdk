import requests as q
from lxml import html
import git
import logging
from contextlib import contextmanager
import os
import shutil

logging.basicConfig(level=logging.DEBUG)


def fetch_sdk_version():
    url = "https://www.foobar2000.org/SDK"
    response = q.get(url)
    response.raise_for_status()  # Raise an error for HTTP issues
    tree = html.fromstring(response.content)

    version_element = tree.xpath("//a[contains(@href, '/getfile/')]")
    if version_element:
        return version_element
    else:
        raise ValueError("Could not find the newest SDK version on the page.")


def fetch_repo():
    repo = git.Repo(".")
    repo.remotes.origin.fetch()
    return repo


@contextmanager
def create_tagged_version_safe(repo, tag_name, ver_link):
    cur_branch = repo.active_branch
    archive_name = "foobar2000-sdk.7z"
    try:
        # create a new branch from the main branch
        new_branch = repo.create_head(tag_name, repo.heads["main"])
        new_branch.checkout()

        # download the SDK version and save it to the repo
        with open(archive_name, "wb") as f:
            response = q.get(ver_link, stream=True)
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # extract the archive with 7z command
        os.system(f"7zz x {archive_name} -y")
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
        if repo.active_branch.name == new_branch.name:
            repo.git.reset("--hard")
            # repo.git.clean("-fd")
            cur_branch.checkout()
            repo.delete_head(new_branch, force=True)
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

if __name__ == "__main__":
    try:
        elements = fetch_sdk_version()[:2]
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
        
    except Exception as e:
        logging.error(f"Error: {e}")
