// Test E2E del dashboard v5 + fix de auth
// Simula lo que haria el navegador real
const http = require('http');

// 1. Hacer GET / con Basic Auth para obtener el HTML
const options = {
    hostname: '100.87.20.4',
    port: 9121,
    path: '/',
    method: 'GET',
    headers: {
        'Authorization': 'Basic ' + Buffer.from('jefe:jefe2026').toString('base64')
    }
};

console.log('=== Test 1: cargar HTML ===');
const req1 = http.request(options, (res) => {
    let html = '';
    res.on('data', d => html += d);
    res.on('end', () => {
        console.log('HTTP', res.statusCode);
        console.log('HTML size:', html.length);

        // 2. Cargar /static/app.js
        console.log('\n=== Test 2: cargar app.js ===');
        const options2 = {
            hostname: '100.87.20.4',
            port: 9121,
            path: '/static/app.js',
            method: 'GET',
            headers: {
                'Authorization': 'Basic ' + Buffer.from('jefe:jefe2026').toString('base64')
            }
        };
        const req2 = http.request(options2, (res2) => {
            let js = '';
            res2.on('data', d => js += d);
            res2.on('end', () => {
                console.log('HTTP', res2.statusCode);
                console.log('JS size:', js.length);
                console.log('Contiene _getAuthHeaders:', (js.match(/_getAuthHeaders/g) || []).length, 'veces');

                // 3. Test fetch SIN auth (como hace el JS bugueado original)
                console.log('\n=== Test 3: fetch SIN auth ===');
                const test_no_auth = (path) => new Promise((resolve) => {
                    const r = http.request({
                        hostname: '100.87.20.4', port: 9121, path: path, method: 'GET'
                    }, (res) => {
                        console.log('  ', path, '-> HTTP', res.statusCode);
                        resolve();
                    });
                    r.end();
                });
                Promise.all([
                    test_no_auth('/api/kpis'),
                    test_no_auth('/api/ingresos-por-mes'),
                    test_no_auth('/api/facturas-recientes'),
                ]).then(() => {
                    // 4. Test fetch CON auth (como hace el JS nuevo)
                    console.log('\n=== Test 4: fetch CON auth ===');
                    const test_with_auth = (path) => new Promise((resolve) => {
                        const r = http.request({
                            hostname: '100.87.20.4', port: 9121, path: path, method: 'GET',
                            headers: { 'Authorization': 'Basic ' + Buffer.from('jefe:jefe2026').toString('base64') }
                        }, (res) => {
                            console.log('  ', path, '-> HTTP', res.statusCode);
                            resolve();
                        });
                        r.end();
                    });
                    return Promise.all([
                        test_with_auth('/api/kpis'),
                        test_with_auth('/api/ingresos-por-mes'),
                        test_with_auth('/api/facturas-recientes'),
                    ]);
                });
            });
        });
        req2.end();
    });
});
req1.end();