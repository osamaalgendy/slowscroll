# Submitting slowscroll to Fedora

1. Done: https://github.com/osamaalgendy/slowscroll is public, tagged `v1.0.1` (latest), with a
   release carrying the noarch RPM and the SRPM (built from GitHub's own tarball;
   checksum verified).
2. Create a Fedora Account (https://accounts.fedoraproject.org) and sign the FPCA.
3. Build and lint locally:
       sudo dnf install rpm-build rpmlint fedora-review mock
       mkdir -p ~/rpmbuild/{SOURCES,SPECS}
       cp slowscroll-1.0.1.tar.gz ~/rpmbuild/SOURCES/ ; cp slowscroll.spec ~/rpmbuild/SPECS/
       rpmbuild -ba ~/rpmbuild/SPECS/slowscroll.spec
       rpmlint -r slowscroll.rpmlintrc ~/rpmbuild/SPECS/slowscroll.spec ~/rpmbuild/RPMS/noarch/*.rpm ~/rpmbuild/SRPMS/*.rpm
4. Done: the Spec and SRPM URLs in `REVIEW-REQUEST.txt` point to the v1.0.1 tag and release.
5. Open the Package Review bug on Bugzilla and paste the text from
   `REVIEW-REQUEST.txt`. First-time packagers also need a sponsor.
