<!doctype html>
<!--
  =====================================================================
  index.html  ―  대시보드 SPA 셸 (Shell)
  ---------------------------------------------------------------------
  • Flask 의 render_template("index.html") 으로 서빙되는 단일 페이지.
  • <div id="root"> 안에 React 가 마운트되어 모든 UI 를 그린다.
  • 빌드 도구 없이 동작하도록 React/ReactDOM/Recharts/Babel 을
    전부 CDN 으로 불러온다. (수행평가 환경에서 npm 설치 없이 즉시 실행 가능)
  =====================================================================
-->
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>하이브리드 EV 파워트레인 + 전자기 회생 서스펜션 시뮬레이터</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />

  <script src="https://cdn.tailwindcss.com"></script>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/prop-types@15/prop-types.min.js"></script>
  <script src="https://unpkg.com/recharts@2.12.7/umd/Recharts.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>

  <link rel="stylesheet" href="/static/style.css" />
</head>
<body class="bg-slate-900 text-slate-100">
  <div id="root"></div>
  <script type="text/babel" src="/static/app.jsx" data-presets="react"></script>
</body>
</html>
