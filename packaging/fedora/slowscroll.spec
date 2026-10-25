Name:           slowscroll
Version:        1.0.1
Release:        1%{?dist}
Summary:        Touchpad scroll speed, acceleration and momentum for libinput

License:        GPL-3.0-or-later
URL:            https://github.com/osamaalgendy/slowscroll
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz

BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  python3dist(evdev)
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib
BuildRequires:  systemd-rpm-macros

Requires:       python3dist(evdev)
Requires:       python3dist(pygobject)
Requires:       gtk4
Requires:       libadwaita
Requires:       systemd

%description
libinput and GNOME have no setting for two-finger touchpad scroll speed.
slowscroll sits between the touchpad and libinput: it grabs the touchpad and
re-emits its events through a virtual touchpad, scaling the movement of two
fingers with a smooth speed-dependent acceleration curve, scaling three-finger
gestures separately, and adding a momentum glide after the fingers lift so that
every application scrolls the same way.

A GTK4/libadwaita settings window (slowscroll-settings) turns the service on and
off and controls the speeds, with a reset button for each setting. The service
is not enabled automatically. After installing, log out and back in (so the
udev rule gives you access to the touchpad), then turn it on in the settings
window.

%prep
%autosetup

%build
# nothing to build

%install
install -Dpm 0755 slowscroll.py %{buildroot}%{_bindir}/slowscroll
install -Dpm 0755 slowscroll-settings.py %{buildroot}%{_bindir}/slowscroll-settings
%py3_shebang_fix %{buildroot}%{_bindir}/slowscroll %{buildroot}%{_bindir}/slowscroll-settings
install -Dpm 0644 slowscroll.service %{buildroot}%{_userunitdir}/slowscroll.service
install -Dpm 0644 70-slowscroll.rules %{buildroot}%{_udevrulesdir}/70-slowscroll.rules
install -Dpm 0644 slowscroll.1 %{buildroot}%{_mandir}/man1/slowscroll.1
install -Dpm 0644 slowscroll-settings.1 %{buildroot}%{_mandir}/man1/slowscroll-settings.1
desktop-file-install --dir=%{buildroot}%{_datadir}/applications \
    io.github.osamaalgendy.Slowscroll.desktop
install -Dpm 0644 io.github.osamaalgendy.Slowscroll.metainfo.xml \
    %{buildroot}%{_metainfodir}/io.github.osamaalgendy.Slowscroll.metainfo.xml

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/io.github.osamaalgendy.Slowscroll.desktop
appstream-util validate-relax --nonet %{buildroot}%{_metainfodir}/io.github.osamaalgendy.Slowscroll.metainfo.xml
%{python3} -m py_compile slowscroll.py slowscroll-settings.py
%{python3} slowscroll.py --curve --config /dev/null >/dev/null
%{python3} tests/test_engine.py slowscroll.py

%post
%systemd_user_post slowscroll.service

%preun
%systemd_user_preun slowscroll.service

%postun
%systemd_user_postun_with_restart slowscroll.service

%files
%license LICENSE
%doc README.md slowscroll.conf.example
%{_bindir}/slowscroll
%{_bindir}/slowscroll-settings
%{_userunitdir}/slowscroll.service
%{_udevrulesdir}/70-slowscroll.rules
%{_datadir}/applications/io.github.osamaalgendy.Slowscroll.desktop
%{_metainfodir}/io.github.osamaalgendy.Slowscroll.metainfo.xml
%{_mandir}/man1/slowscroll.1*
%{_mandir}/man1/slowscroll-settings.1*

%changelog
* Mon Oct 26 2026 Osama Algendy <71908505+osamaalgendy@users.noreply.github.com> - 1.0.1-1
- Keep the virtual touchpad at the real pad's size; glides that reach the
  edge are handed over to the app's own kinetic scrolling

* Sun Oct 25 2026 Osama Algendy <71908505+osamaalgendy@users.noreply.github.com> - 1.0.0-1
- Initial package
