const homeNavigation = document.querySelector('[data-home-navigation]');

if (homeNavigation) {
    const toggle = homeNavigation.querySelector('.home-nav-toggle');
    const links = homeNavigation.querySelector('.home-nav-links');

    function setOpen(open) {
        links.hidden = !open;
        toggle.setAttribute('aria-expanded', String(open));
    }

    homeNavigation.addEventListener('pointerenter', event => {
        if (event.pointerType === 'mouse') setOpen(true);
    });
    homeNavigation.addEventListener('pointerleave', event => {
        if (event.pointerType === 'mouse' && !links.contains(document.activeElement)) setOpen(false);
    });
    toggle.addEventListener('click', () => setOpen(links.hidden));
    homeNavigation.addEventListener('focusout', event => {
        if (!homeNavigation.contains(event.relatedTarget)) setOpen(false);
    });
    homeNavigation.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !links.hidden) {
            setOpen(false);
            toggle.focus();
        }
    });
    document.addEventListener('pointerdown', event => {
        if (!homeNavigation.contains(event.target)) setOpen(false);
    });
}
