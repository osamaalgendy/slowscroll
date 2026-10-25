# Submitting slowscroll to Fedora

1. Upstream repo: https://github.com/osamaalgendy/slowscroll (private for now).
   Fedora reviewers must be able to download the source, so make it public and tag
   `v1.0.0` before submitting. `URL:` in `slowscroll.spec` already points to it.
2. Create a Fedora Account (https://accounts.fedoraproject.org) and sign the FPCA.
3. Build and lint locally:
       sudo dnf install rpm-build rpmlint fedora-review mock
       mkdir -p ~/rpmbuild/{SOURCES,SPECS}
       cp slowscroll-1.0.0.tar.gz ~/rpmbuild/SOURCES/ ; cp slowscroll.spec ~/rpmbuild/SPECS/
       rpmbuild -ba ~/rpmbuild/SPECS/slowscroll.spec
       rpmlint ~/rpmbuild/SPECS/slowscroll.spec ~/rpmbuild/RPMS/noarch/*.rpm ~/rpmbuild/SRPMS/*.rpm
4. Host the .spec and .src.rpm (easiest: a Copr build or a GitHub release) and
   put the URLs in `REVIEW-REQUEST.txt`.
5. Open the Package Review bug on Bugzilla and paste the text from
   `REVIEW-REQUEST.txt`. First-time packagers also need a sponsor.
